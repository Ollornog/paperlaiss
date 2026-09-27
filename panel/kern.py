#!/usr/bin/env python3
"""Reine Logik des Panels — ohne FastAPI, ohne Netz, ohne Dateisystem.

Warum getrennt: `app.py` laesst sich nur mit installiertem FastAPI importieren, die Testsuite
des Projekts ist aber stdlib-only. Alles, was eine Entscheidung trifft und ohne Netz auskommt,
steht deshalb hier und wird von `app.py` importiert. So ist es testbar, statt ungeprueft zu
bleiben — dieselbe Lehre wie bei `build_cfs` im Klassifizierer.
"""
import json
import re

# Die ID steckt je nach Webhook-Einstellung im Pfad (`{{doc_url}}`) oder als Feld.
DOC_ID_IM_TEXT = re.compile(r"/documents/(\d+)|\"doc_id\"\s*:\s*\"?(\d+)|\bdoc(?:ument)?[_-]?id\b\D{0,4}(\d+)")


def doc_id_aus_webhook(rohtext):
    """Dokument-ID aus einem Paperless-Webhook fischen — egal in welcher Form sie ankommt.

    Mit `as_json=true` UND gesetztem `body` sendet Paperless den gerenderten String als
    JSON-WERT: Content-Type application/json, Rumpf `"{\\"doc_id\\": \\"919\\"}"` — also JSON,
    das JSON enthaelt, zweimal zu parsen. Mit `use_params=true` kommt ein sauberes Objekt.
    Statt eine Form vorzuschreiben, lesen wir beide und fallen auf eine Textsuche zurueck.

    Gibt die ID als int zurueck oder None.
    """
    kandidat = rohtext
    for _ in range(2):                       # hoechstens zweimal auspacken
        try:
            g = json.loads(kandidat)
        except (ValueError, TypeError):
            break
        if isinstance(g, str):
            kandidat = g
            continue
        if isinstance(g, dict):
            for schluessel in ("doc_id", "document_id", "id"):
                wert = str(g.get(schluessel, "")).strip()
                if wert.isdigit():
                    return int(wert)
            kandidat = json.dumps(g)
        break
    m = DOC_ID_IM_TEXT.search(str(kandidat))
    if m:
        return int(next(g for g in m.groups() if g))
    return None


def feld_typ(wert):
    """Welches Eingabeelement passt zu diesem Konfigurationswert?

    Die Konfiguration ist gewachsen und gemischt: Wahrheitswerte, Zahlen, kurze Zeichenketten,
    lange Texte (der System-Prompt), Listen und ein Wörterbuch. Statt jedes Feld einzeln zu
    pflegen — was bei jedem neuen Schlüssel vergessen würde — wird der Typ aus dem aktuellen
    Wert abgeleitet.
    """
    if isinstance(wert, bool):
        return "bool"
    if isinstance(wert, (int, float)):
        return "zahl"
    if isinstance(wert, (list, dict)):
        return "json"
    if isinstance(wert, str) and (len(wert) > 120 or "\n" in wert):
        return "text"
    return "zeile"


def config_uebernehmen(alt, eingaben):
    """Formulareingaben (alles Text) zurück in die Typen der Konfiguration bringen.

    Ein Formular liefert Zeichenketten. Würde man die ungeprüft speichern, stünde nach dem
    ersten Speichern `"true"` statt `true` und `"300"` statt `300` in der Datei — der
    Klassifizierer liest dann eine Zeichenkette, wo er eine Zahl erwartet, und das fällt erst
    im Betrieb auf.

    Der TYP DES BISHERIGEN WERTES gibt die Richtung vor. Was sich nicht umwandeln lässt, wird
    ÜBERGANGEN statt geraten — ein Tippfehler im Formular darf keinen Schlüssel zerstören.
    Rückgabe: (neue_config, liste_der_uebergangenen_felder).
    """
    neu = dict(alt)
    uebergangen = []
    for schluessel, eingabe in (eingaben or {}).items():
        if schluessel not in alt:
            uebergangen.append(f"{schluessel} (unbekannt)")
            continue
        art = feld_typ(alt[schluessel])
        try:
            if art == "bool":
                neu[schluessel] = eingabe if isinstance(eingabe, bool) else \
                    str(eingabe).strip().lower() in ("true", "1", "ja", "an", "on")
            elif art == "zahl":
                roh = str(eingabe).strip().replace(",", ".")
                neu[schluessel] = float(roh) if isinstance(alt[schluessel], float) else int(float(roh))
            elif art == "json":
                wert = json.loads(eingabe) if isinstance(eingabe, str) else eingabe
                if not isinstance(wert, type(alt[schluessel])):
                    uebergangen.append(f"{schluessel} (erwartet {type(alt[schluessel]).__name__})")
                    continue
                neu[schluessel] = wert
            else:
                neu[schluessel] = str(eingabe)
        except (ValueError, TypeError) as e:
            uebergangen.append(f"{schluessel} ({e.__class__.__name__})")
    return neu, uebergangen


# Was eine Logzeile bedeutet — die Reihenfolge entscheidet, weil "OCR-rescue-fail" auch
# "OCR-rescue" enthaelt und "repair-fehlgeschlagen" auch "repariert".
LOG_ARTEN = (
    ("OCR-rescue-fail", "fehler"),
    ("repair-fehlgeschlagen", "fehler"),
    ("patch-fail", "fehler"),
    ("KI-OCR-fail", "fehler"),
    ("pass0-fail", "fehler"),
    ("nachbearbeitung-fail", "fehler"),
    ("trace-fail", "fehler"),
    ("OCR-nachgeholt-fail", "fehler"),
    ("OCR-neu-fail", "fehler"),
    ("FEHLER", "fehler"),
    ("OCR-rescue", "ocr"),
    ("OCR-nachgeholt", "ocr"),
    ("OCR-neu", "ocr"),
    ("repariert", "repariert"),
    ("VORSCHLAG", "vorschlag"),
    ("skip", "uebersprungen"),
    ("OK", "klassifiziert"),
)


def log_art(zeile):
    """Welche Art von Ereignis beschreibt diese Logzeile?

    Entscheidend ist das ERSTE Wort — es nennt das Ereignis. Bis 2026-09-27 wurde nur nach
    Teiltexten gesucht, und die Erfolgszeile eines Laufs mit OCR („OK 913 | … | OCR-rescue(340)")
    traf zuerst auf „OCR-rescue": jeder Lauf mit OCR fehlte bei „klassifiziert" und zählte doppelt
    als OCR. Die Teiltextsuche bleibt als Rückfall für Zeilen ohne bekanntes erstes Wort.
    """
    erstes = (zeile or "").split(maxsplit=1)[0] if (zeile or "").strip() else ""
    if erstes == "OK":
        return "klassifiziert"
    if erstes == "VORSCHLAG":
        return "vorschlag"
    if erstes == "skip":
        return "uebersprungen"
    if erstes == "repariert":
        return "repariert"
    if erstes.startswith("FEHLER") or erstes.endswith("-fail") or erstes.endswith("fehlgeschlagen"):
        return "fehler"
    if erstes.startswith("OCR-"):
        return "ocr"
    if erstes == "DRY":
        return None
    for muster, art in LOG_ARTEN:
        if muster in zeile:
            return art
    return None


def verlauf(zeilen, tage=30, heute=None):
    """Taegliche Zaehlung je Ereignisart, aelteste zuerst.

    Erwartet Logzeilen der Form "JJJJ-MM-TT HH:MM:SS <text>". Zeilen ohne Datum werden
    uebergangen; ein unlesbares Log soll keine Auswertung sprengen.

    `heute` ist ein Datum als Text (JJJJ-MM-TT) und wird nur zum Abschneiden gebraucht —
    ohne Angabe wird der spaeteste im Log gefundene Tag genommen. So bleibt die Funktion
    ohne Uhr testbar und liefert bei einem alten Log trotzdem etwas Sinnvolles.
    """
    proTag = {}
    for zeile in zeilen or []:
        if len(zeile) < 19 or zeile[4] != "-" or zeile[7] != "-":
            continue
        tag = zeile[:10]
        art = log_art(zeile[20:])
        if not art:
            continue
        proTag.setdefault(tag, {}).setdefault(art, 0)
        proTag[tag][art] += 1
    if not proTag:
        return []
    letzter = heute or max(proTag)
    # Luecken auffuellen: ein Verlauf ohne leere Tage ist eine Liste, keine Kurve. Gerade die
    # Luecke ist oft die Aussage — "seit drei Wochen laeuft nichts" sieht man nur, wenn die
    # leeren Tage da sind.
    import datetime as _dt
    ende = _dt.date.fromisoformat(letzter)
    start = ende - _dt.timedelta(days=tage - 1)
    frueheste = _dt.date.fromisoformat(min(proTag))
    if frueheste > start:
        start = frueheste
    out, tag = [], start
    while tag <= ende:
        schluessel = tag.isoformat()
        out.append({"tag": schluessel, **proTag.get(schluessel, {})})
        tag += _dt.timedelta(days=1)
    return out


def auffaelligkeiten(zeilen, geloest_nach=None):
    """Fehlerzeilen, und ob sie inzwischen geloest sind.

    „Geloest" heisst: fuer dasselbe Dokument gibt es SPAETER einen erfolgreichen Lauf. Ohne
    diese Unterscheidung steht ein Fehler vom Juli ewig in der Liste, obwohl er am selben Tag
    behoben wurde — und eine Liste, in der alles steht, liest irgendwann niemand mehr.
    """
    import re
    doc_re = re.compile(r"\b(?:OK|VORSCHLAG|skip|FEHLER|OCR-rescue|OCR-rescue-fail|patch-fail|"
                        r"repariert|repair-fehlgeschlagen|KI-OCR-fail)\s+(\d+)")
    erfolg_zuletzt = {}
    for zeile in zeilen or []:
        if len(zeile) < 19:
            continue
        art = log_art(zeile[20:])
        m = doc_re.search(zeile[20:])
        if art in ("klassifiziert", "vorschlag") and m:
            erfolg_zuletzt[m.group(1)] = zeile[:19]
    out = []
    for zeile in zeilen or []:
        if len(zeile) < 19 or log_art(zeile[20:]) != "fehler":
            continue
        m = doc_re.search(zeile[20:])
        doc = m.group(1) if m else None
        ts = zeile[:19]
        out.append({"ts": ts, "doc": doc, "text": zeile[20:].strip()[:200],
                    "geloest": bool(doc and erfolg_zuletzt.get(doc, "") > ts)})
    out.sort(key=lambda e: e["ts"], reverse=True)
    return out


def auth_einstellungen(env):
    """Wie sich das Panel anmeldet — aus der Umgebung gelesen, ohne etwas zu importieren.

    Drei Modi ueber PANEL_AUTH:
      ""          (Vorgabe) Bearer-Token PANEL_TOKEN bzw. Cookie panel_token
      "none"      keine eigene Anmeldung, weil eine davorhaengt
      "tinysesam" Anmeldeseite von TinySesam: PocketID/OIDC und, nur wenn ausdruecklich
                  eingeschaltet, Benutzername + Passwort (zum Debuggen im Testbett)

    Rueckgabe: {"modus", "tinysesam": Keyword-Argumente fuer TinySesamConfig oder None,
    "admin": (name, passwort) oder None, "fehler": [..]}. Fehler heisst: das Panel darf so
    nicht starten — eine Anmeldung, die still in einen offenen oder unbenutzbaren Zustand
    faellt, ist schlimmer als ein Container, der mit einer klaren Meldung aussteigt.
    """
    from urllib.parse import urlsplit
    modus = (env.get("PANEL_AUTH") or "").strip().lower()
    out = {"modus": modus, "tinysesam": None, "admin": None, "fehler": []}
    if modus in ("", "none"):
        return out
    if modus != "tinysesam":
        out["fehler"].append(f"PANEL_AUTH={modus!r} unbekannt — erlaubt: leer, none, tinysesam")
        return out

    base = (env.get("PANEL_BASE_URL") or "").strip().rstrip("/")
    teile = urlsplit(base)
    if teile.scheme not in ("http", "https") or not teile.hostname:
        out["fehler"].append("PANEL_BASE_URL fehlt oder ist keine http(s)-Adresse — TinySesam "
                             "braucht sie für Weiterleitungen und den OIDC-Rückruf")
        return out
    https = teile.scheme == "https"
    passwort = (env.get("PANEL_PASSWORD_LOGIN") or "").strip().lower() in ("1", "true", "ja", "yes")
    issuer = (env.get("PANEL_OIDC_ISSUER") or "").strip()
    client_id = (env.get("PANEL_OIDC_CLIENT_ID") or "").strip()
    secret = (env.get("PANEL_OIDC_CLIENT_SECRET") or "").strip()
    oidc_teile = [bool(issuer), bool(client_id), bool(secret)]
    oidc = all(oidc_teile)
    if any(oidc_teile) and not oidc:
        out["fehler"].append("PocketID/OIDC halb konfiguriert — PANEL_OIDC_ISSUER, "
                             "PANEL_OIDC_CLIENT_ID und PANEL_OIDC_CLIENT_SECRET gehören zusammen")
    if not oidc and not passwort:
        out["fehler"].append("PANEL_AUTH=tinysesam ohne Anmeldeweg — OIDC konfigurieren oder "
                             "PANEL_PASSWORD_LOGIN=1 setzen")
    cfg = {
        "db_path": (env.get("PANEL_AUTH_DB") or "/auth/tinysesam.db").strip(),
        "lang": "de",
        "rp_name": "paperlaiss",        # Titel der Anmeldeseite (sonst „TinySesam")
        # Projektbild gross ueber den eingebauten Seiten (Anmeldung, Konto); /logo.png liefert
        # das Panel ohne Anmeldung aus. Zentriert per brand_css statt style-Attribut — die CSP
        # von TinySesam laesst Inline-Styles nicht zu.
        "brand_icon": "/logo.png",
        "brand_header": '<div class="pl-logo"><img src="/logo.png" alt="paperlaiss" width="160" height="160"></div>',
        # Logo und Karte als EIN Block mittig: TinySesam gibt .tsmain sonst die ganze Resthoehe
        # (flex:1) und zentriert die Karte darin — das Logo bliebe oben kleben.
        "brand_css": ("body{justify-content:center}.tsmain{flex:0 0 auto}"
                      ".pl-logo{text-align:center;margin:0 0 -12px}"
                      ".pl-credit{text-align:center;font-size:11px;opacity:.6;margin:18px 0}"
                      ".pl-credit a{color:inherit}"),
        # Bildnachweis dort, wo das Bild oeffentlich zu sehen ist (Lizenz des Icons).
        "brand_footer": ('<p class="pl-credit">Icon: <a href="https://www.flaticon.com/authors/magnific" '
                         'rel="noopener">Origami by Magnific – flaticon.com</a></p>'),
        "base_url": base,
        "origin": f"{teile.scheme}://{teile.netloc}",
        "rp_id": teile.hostname,
        # Ueber http gibt es kein Secure-Cookie; TinySesam erlaubt das nur, wenn man es sagt.
        "cookie_secure": https,
        "https_mode": "warn" if https else "off",
        "password_enabled": passwort,
        "oidc_enabled": oidc,
        # Keine Selbstregistrierung: wer hier hinein darf, legt der Admin an bzw. die PocketID fest.
        "allow_signup": False,
    }
    if oidc:
        cfg.update({"oidc_issuer": issuer, "oidc_client_id": client_id,
                    "oidc_client_secret": secret,
                    "oidc_name": (env.get("PANEL_OIDC_NAME") or "PocketID").strip()})
        # Leer = jeder, den die PocketID durchlaesst (Freigabe dort ueber die Gruppen am Client).
        gruppen = [g.strip() for g in (env.get("PANEL_OIDC_GROUPS") or "").split(",") if g.strip()]
        if gruppen:
            cfg["oidc_allowed_groups"] = gruppen
    out["tinysesam"] = cfg
    name = (env.get("PANEL_ADMIN_USER") or "").strip()
    pw = env.get("PANEL_ADMIN_PASSWORD") or ""
    if name and pw:
        if not passwort:
            out["fehler"].append("PANEL_ADMIN_USER/PANEL_ADMIN_PASSWORD gesetzt, aber "
                                 "PANEL_PASSWORD_LOGIN aus — das Konto könnte sich nie anmelden")
        out["admin"] = (name, pw)
    return out


def ausloeser_auswerten(tags, custom_fields, redo_id, ocr_id, hinweis_fid, marker_id=None):
    """Was hat der Nutzer in Paperless ausgeloest, und was muss vor dem Lauf weg?

    Drei Auslöser: Tag „neu klassifizieren", Hinweisfeld mit Text, Tag „nur OCR".
    Rueckgabe (modus, hinweis, patch):
      modus  "neu"      — neu klassifizieren (mit OCR); gewinnt, wenn mehrere gesetzt sind,
                          denn der Lauf liest ohnehin per OCR neu
             "nur_ocr"  — nur den Text neu lesen
             None       — nichts ausgeloest (der Webhook kam von einer anderen Aenderung)
      patch  — entfernt BEIDE Tags und das Hinweisfeld, sonst loest die naechste Bearbeitung
               erneut aus. Leer, wenn nichts zu entfernen ist.

    Beim reinen OCR bleibt der OCR-Tag stehen: der Lauf entfernt ihn erst zusammen mit dem
    neuen Text, und das ist das Fertig-Signal fuer den Knopf (ein unveraenderter Text aendert
    das Dokument sonst gar nicht). Beim Neu-Klassifizieren geht auch der Marker-Tag mit weg; der Lauf setzt ihn am Ende wieder.
    Daran erkennt der KI-Knopf in Paperless, dass das ERGEBNIS da ist — „das Dokument hat sich
    geaendert" genuegt nicht, denn der OCR-Text wird schon vorher geschrieben.
    """
    tags = list(tags or [])
    cfs = list(custom_fields or [])
    hinweis = ""
    if hinweis_fid:
        for c in cfs:
            if c.get("field") == hinweis_fid:
                hinweis = str(c.get("value") or "").strip()
    neu = bool(redo_id) and redo_id in tags
    ocr = bool(ocr_id) and ocr_id in tags
    patch = {}
    if neu or hinweis:
        weg = {x for x in (redo_id, ocr_id, marker_id) if x}
    else:
        weg = set()
    rest = [t for t in tags if t not in weg]
    if len(rest) != len(tags):
        patch["tags"] = rest
    if hinweis:
        patch["custom_fields"] = [c for c in cfs if c.get("field") != hinweis_fid]
    modus = "neu" if (neu or hinweis) else "nur_ocr" if ocr else None
    return modus, hinweis, patch


# Die fünf Arten, die das Panel oben als Kennzahl zeigt und nach denen es filtert — dieselbe
# Einordnung wie log_art(), damit Zahl und gefilterte Liste nie auseinanderlaufen.
KENNZAHL_ARTEN = ("klassifiziert", "ocr", "repariert", "fehler", "uebersprungen")
_DOC = None


def eintrag_lesen(zeile):
    """Eine Protokollzeile als Eintrag für die Aktivitätsliste — oder None ohne Zeitstempel.

    Die Rohzeile ist für den Klassifizierer geschrieben („OK 913 | exakt='X' id=13 | typ=21 | …").
    Für die Liste werden die Teile herausgelöst, die man beim Überfliegen braucht; die Rohzeile
    bleibt als `text` erhalten, damit nichts verloren geht.
    """
    import re
    global _DOC
    if _DOC is None:
        _DOC = re.compile(r"^\S+(?:\s+\S+)?\s+(\d+)\b")
    if len(zeile) < 20 or zeile[4] != "-" or zeile[7] != "-" or zeile[13] != ":":
        return None
    rest = zeile[20:].strip()
    art = log_art(rest) or "info"
    m = re.match(r"^(?:DRY\s+)?[A-Za-z-]+\s+(\d+)\b", rest)
    doc = int(m.group(1)) if m else None
    korr = re.search(r"(exakt|NEU|kandidat\w*)='([^']*)'", rest)
    typ = re.search(r"\btyp=(\d+|[^|\s][^|]*?)\s*(?:\||$)", rest)
    ocr = re.search(r"(OCR-[a-z]+\((\d+)\))", rest)
    return {"ts": zeile[:19], "tag": zeile[:10], "art": art, "doc": doc,
            "korrespondent": korr.group(2) if korr else None,
            "korrespondent_neu": bool(korr and korr.group(1) == "NEU"),
            "typ": typ.group(1).strip() if typ else None,
            "ocr": ocr.group(1) if ocr else None,
            "text": rest[:400]}


def aktivitaet(zeilen, art=None, tag=None, doc=None, seite=1, je=100):
    """Die Aktivitätsliste, neueste zuerst, gefiltert und in Seiten zu `je` Einträgen.

    Filter lassen sich kombinieren (Art UND Tag UND Dokument). `seite` wird in den gültigen
    Bereich gezogen, damit ein veralteter Link auf „Seite 9" nach einem Filter nicht ins Leere
    zeigt. `kennzahlen` zählt über ALLE Zeilen, nicht über die gefilterten — die Kästen oben
    sind die Einstiege in die Filter und dürfen nicht mitschrumpfen.
    """
    alle = [e for e in (eintrag_lesen(z) for z in (zeilen or [])) if e]
    kennzahlen = {a: 0 for a in KENNZAHL_ARTEN}
    for e in alle:
        if e["art"] in kennzahlen:
            kennzahlen[e["art"]] += 1
    treffer = [e for e in reversed(alle)
               if (not art or e["art"] == art) and (not tag or e["tag"] == tag)
               and (doc is None or e["doc"] == doc)]
    je = max(1, int(je))
    seiten = max(1, -(-len(treffer) // je))
    seite = min(max(1, int(seite)), seiten)
    return {"eintraege": treffer[(seite - 1) * je: seite * je], "gesamt": len(treffer),
            "seite": seite, "seiten": seiten, "je": je, "kennzahlen": kennzahlen,
            "filter": {"art": art, "tag": tag, "doc": doc}}
