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
