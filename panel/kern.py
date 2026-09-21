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


def doc_hat_sich_geaendert(vorschlag, doc):
    """Hat sich das Dokument seit der Erzeugung des Vorschlags geaendert?

    Ohne diese Pruefung ueberschreibt ein alter Vorschlag stillschweigend eine Korrektur, die
    jemand zwischenzeitlich von Hand gemacht hat. Verglichen wird der `modified`-Zeitstempel;
    fehlt er auf einer der beiden Seiten, die inhaltlichen Felder.
    """
    stand = vorschlag.get("stand") or {}
    if stand.get("modified") and doc.get("modified"):
        return stand["modified"] != doc["modified"]
    jetzt = {"title": doc.get("title"), "correspondent": doc.get("correspondent"),
             "document_type": doc.get("document_type"), "created": (doc.get("created") or "")[:10],
             "tags": sorted(doc.get("tags") or [])}
    vorher = {k: stand.get(k) for k in jetzt}
    vorher["tags"] = sorted(vorher.get("tags") or [])
    vorher["created"] = (vorher.get("created") or "")[:10]
    return jetzt != vorher


# Felder des Korrespondent-Stores, die beim Zusammenführen als Liste behandelt werden:
# hier gehen Werte nicht verloren, sondern werden vereinigt.
LISTENFELDER = ("domains", "aliase")


def merge_metadaten(ziel, quellen, listenfelder=LISTENFELDER):
    """Mehrere Store-Einträge zu einem verschmelzen.

    Regeln, in dieser Reihenfolge:
      1. Was im ZIEL steht, bleibt. Wer zwei Kundennummern hat, will die des Ziels behalten —
         alles andere wäre eine stille Entscheidung über Kundendaten.
      2. Leere Zielfelder werden aus der ersten Quelle gefüllt, die etwas hat.
      3. Listenfelder (Domains, Aliase) werden VEREINIGT statt überschrieben. Genau dafür sind
         sie da: Ein zusammengeführter Korrespondent soll unter allen bisherigen Namen und
         Absenderdomains wiedergefunden werden, sonst legt der Feedback-Loop ihn neu an.

    Die Reihenfolge der Listeneinträge bleibt stabil (Ziel zuerst, dann Quellen), Dubletten
    fallen raus — ohne Rücksicht auf Groß-/Kleinschreibung, aber mit der zuerst gesehenen
    Schreibweise.
    """
    ergebnis = dict(ziel or {})
    for feld in listenfelder:
        gesehen, werte = set(), []
        for eintrag in [ziel or {}] + list(quellen or []):
            for teil in str((eintrag or {}).get(feld) or "").split(","):
                teil = teil.strip()
                if teil and teil.lower() not in gesehen:
                    gesehen.add(teil.lower())
                    werte.append(teil)
        if werte:
            ergebnis[feld] = ", ".join(werte)
    for quelle in (quellen or []):
        for feld, wert in (quelle or {}).items():
            if feld in listenfelder:
                continue
            if not str(ergebnis.get(feld) or "").strip() and str(wert or "").strip():
                ergebnis[feld] = wert
    return {k: v for k, v in ergebnis.items() if str(v or "").strip()}


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
    ("FEHLER", "fehler"),
    ("OCR-rescue", "ocr"),
    ("repariert", "repariert"),
    ("VORSCHLAG", "vorschlag"),
    ("skip", "uebersprungen"),
    ("OK", "klassifiziert"),
)


def log_art(zeile):
    """Welche Art von Ereignis beschreibt diese Logzeile?"""
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
