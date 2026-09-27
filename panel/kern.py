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


def panel_pfad(env) -> str:
    """Der Pfad, unter dem das Panel im Browser erreichbar ist (`PANEL_PFAD`, etwa `/paperlaiss`
    hinter derselben Domain wie Paperless). Leer = an der Wurzel. Nur einfache Pfadteile — der Wert
    landet in HTML und JavaScript; alles andere zählt als leer, und die Anmeldeprüfung meldet dann,
    dass er nicht zu PANEL_BASE_URL passt."""
    p = (env.get("PANEL_PFAD") or "").strip().rstrip("/")
    return p if re.fullmatch(r"(/[A-Za-z0-9._-]+)*", p) else ""


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
    if teile.path.rstrip("/") != panel_pfad(env):
        out["fehler"].append(f"PANEL_BASE_URL endet auf {teile.path or '/'!r}, PANEL_PFAD ist "
                             f"{panel_pfad(env) or '/'!r} — beide müssen denselben Pfad nennen, sonst "
                             "führen Anmeldung und Rückruf ins Leere")
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
        "brand_icon": panel_pfad(env) + "/logo.png",
        "brand_header": ('<div class="pl-logo"><img src="' + panel_pfad(env)
                         + '/logo.png" alt="paperlaiss" width="160" height="160"></div>'),
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
        # Kein Einmal-Token für den TinySesam-Admin: das Panel braucht keinen (Zugang über die
        # PocketID-Gruppe bzw. PANEL_ADMIN_USER), und TinySesam schrieb ihn bei jedem Start ohne
        # Admin ins Container-Log (2026-09-27, PO: „einfach entfernen").
        "admin_claim_ttl_min": 0,
    }
    if oidc:
        cfg.update({"oidc_issuer": issuer, "oidc_client_id": client_id,
                    "oidc_client_secret": secret,
                    "oidc_name": (env.get("PANEL_OIDC_NAME") or "PocketID").strip()})
        # Leer = jeder, den die PocketID durchlaesst (Freigabe dort ueber die Gruppen am Client).
        gruppen = [g.strip() for g in (env.get("PANEL_OIDC_GROUPS") or "").split(",") if g.strip()]
        if gruppen:
            cfg["oidc_allowed_groups"] = gruppen
            # Ohne den Scope `groups` schickt PocketID keine Gruppen mit — dann käme bei gesetzter
            # Gruppensperre niemand hinein, auch der Admin nicht.
            cfg["oidc_scopes"] = "openid profile email groups"
    # Hinter einem Reverse-Proxy im Container ist der direkte Peer nie 127.0.0.1 (TinySesams Vorgabe).
    # Ohne diese Liste wertet TinySesam X-Forwarded-For nicht aus, und alle Nutzer erscheinen unter
    # der Proxy-IP — Rate-Limit, IP-Sperre und Audit-Log gelten dann für alle gemeinsam (2026-09-27,
    # Warnung von TinySesam im Produktivlog). Einzutragen sind ALLE Proxys der Kette: TinySesam nimmt die
    # rechteste Adresse, die nicht in der Liste steht.
    proxies = [p.strip() for p in (env.get("PANEL_TRUSTED_PROXIES") or "").split(",") if p.strip()]
    if proxies:
        import ipaddress
        schlecht = []
        for p in proxies:
            try:
                ipaddress.ip_network(p, strict=False)
            except ValueError:
                schlecht.append(p)
        if schlecht:
            out["fehler"].append(f"PANEL_TRUSTED_PROXIES enthält Einträge, die kein IP-Netz sind: {schlecht} "
                                 "— erwartet z. B. 172.16.0.0/12,192.0.2.1/32")
        cfg["trusted_proxies"] = proxies
    out["tinysesam"] = cfg
    name = (env.get("PANEL_ADMIN_USER") or "").strip()
    pw = env.get("PANEL_ADMIN_PASSWORD") or ""
    if name and pw:
        if not passwort:
            out["fehler"].append("PANEL_ADMIN_USER/PANEL_ADMIN_PASSWORD gesetzt, aber "
                                 "PANEL_PASSWORD_LOGIN aus — das Konto könnte sich nie anmelden")
        out["admin"] = (name, pw)
    return out


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
    # Trockenläufe (DRY) haben nichts geschrieben — eigene Art, damit man sie nicht für Fehler
    # oder echte Läufe hält. Alles Übrige ohne bekanntes erstes Wort ist ein Hinweis.
    art = "trockenlauf" if rest.startswith("DRY") else (log_art(rest) or "hinweis")
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


def knopf_rechte(antwort, gewuenscht):
    """Welche der gewünschten Dokumente darf der angemeldete Paperless-Nutzer ändern?

    `antwort` ist die JSON-Antwort von `GET /api/documents/?id__in=…&fields=id,user_can_change`,
    abgefragt MIT der Sitzung des Nutzers. Ein Dokument, das dort fehlt, darf er nicht einmal
    sehen — es zählt als verweigert, nicht als erlaubt. Rückgabe: (erlaubt, verweigert), sortiert.
    """
    darf = {int(d["id"]) for d in (antwort or {}).get("results", []) if d.get("user_can_change")}
    gewuenscht = sorted({int(x) for x in gewuenscht})
    return [d for d in gewuenscht if d in darf], [d for d in gewuenscht if d not in darf]


# Die Felder des Adressbuchs (correspondents.json), die der Korrespondenten-Dialog in Paperless
# zeigt — Name, Beschriftung, mehrzeilig. Mehrere Werte (Domains, Aliase) stehen kommagetrennt,
# so liest sie classify.py (calias, Domain-Abgleich).
KORR_FELDER = (
    ("kontext", "Kontext für die KI", True),
    ("aliase", "Andere Schreibweisen (kommagetrennt)", False),
    ("email", "E-Mail", False),
    ("domains", "Mail-Domains (kommagetrennt)", False),
    ("kundennummer", "Unsere Kundennummer dort", False),
    ("ustid", "USt-ID", False),
    ("iban", "IBAN", False),
    ("telefon", "Telefon", False),
    ("adresse", "Adresse", True),
)


def korr_eintrag(alt, eingabe):
    """Einen Adressbuch-Eintrag aus der Formulareingabe bilden.

    Nur bekannte Felder, Werte als getrimmter Text, leere Felder fallen weg. Was der Dialog nicht
    kennt (`quelle`, `extern_id` aus einem Import), bleibt erhalten — sonst löschte jedes
    Speichern im Dialog die Herkunft eines importierten Eintrags.
    """
    alt = alt or {}
    neu = {k: v for k, v in alt.items() if k not in {f for f, _, _ in KORR_FELDER}}
    erfasst = dict(alt.get("erfasst") or {})
    for feld, _, _ in KORR_FELDER:
        wert = str((eingabe or {}).get(feld) or "").strip()
        if wert:
            neu[feld] = wert[:4000]
        # Von Hand geändert oder geleert: der Wert stammt nicht mehr von der KI.
        if wert != str(alt.get(feld) or "").strip():
            erfasst.pop(feld, None)
    if erfasst:
        neu["erfasst"] = erfasst
    else:
        neu.pop("erfasst", None)
    return neu


# ---- KI-Knopf: Sperre gegen Doppelstart und Fortschritt fürs Paperless-Fenster ----
# Die Schritte meldet classify.py über set_stage() in scripts/running/<id>.json. Der Prozentwert ist
# eine Schätzung nach der Reihenfolge der Schritte, keine gemessene Restzeit.
KNOPF_SCHRITTE = (
    ("OCR-Rescue", "Text per OCR lesen", 15), ("Kandidaten", "Korrespondenten suchen", 30),
    ("Pass 1", "KI analysiert das Dokument", 50), ("OCR-Nachlauf", "OCR nachholen, erneut analysieren", 60),
    ("Korrespondent", "Korrespondent zuordnen", 75), ("Tags & Schreiben", "In Paperless schreiben", 90),
    ("Feld-Korrektur", "Felder korrigieren", 93),
)
_KNOPF_AKTIV = ("wartet", "laeuft")


def knopf_annehmen(jobs, ids):
    """(starten, laeuft_schon): ein Dokument, das schon wartet oder läuft, wird nicht noch einmal
    angenommen — ein zweiter Klick, ein zweiter Tab oder ein Kollege startet sonst einen zweiten Lauf
    auf dasselbe Dokument, und der spätere überschreibt den früheren."""
    starten, schon = [], []
    for d in ids:
        (schon if (jobs.get(d) or {}).get("status") in _KNOPF_AKTIV else starten).append(d)
    return starten, schon


def knopf_fortschritt(status, stufe=None):
    """{"status", "schritt", "prozent"} für die Anzeige in Paperless."""
    if status == "wartet":
        return {"status": status, "schritt": "wartet auf einen freien Platz", "prozent": 3}
    if status == "laeuft":
        for name, text, prozent in KNOPF_SCHRITTE:
            if stufe and str(stufe).startswith(name):
                return {"status": status, "schritt": text, "prozent": prozent}
        return {"status": status, "schritt": "startet", "prozent": 8}
    if status == "fertig":
        return {"status": status, "schritt": "fertig", "prozent": 100}
    return {"status": status, "schritt": status, "prozent": 100 if status == "fehler" else 0}
