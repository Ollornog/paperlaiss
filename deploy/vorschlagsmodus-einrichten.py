#!/usr/bin/env python3
"""Richtet den Vorschlagsmodus in einer Paperless-Instanz ein — idempotent.

Legt an, was der Zauberstab-Weg braucht, und traegt es in die classify-config.json ein:

  1. Auslöser-Tag      (Standard „KI-neu")      — dranhängen = neu verarbeiten lassen
  2. Hinweis-Feld      (Standard „KI-Hinweis")  — optionaler Freitext für den Lauf
  3. Paperless-Workflow „Document Updated" mit zwei Auslösern (Tag bzw. Feld befüllt),
     Aktion = Webhook auf das Panel

Zweimal laufen lassen ändert nichts — bestehende Objekte werden wiederverwendet.

  PAPERLESS_API   z.B. http://localhost:8000/api
  PAPERLESS_TOKEN API-Token eines Benutzers mit Rechten auf Tags/Felder/Workflows
  PANEL_URL       wie Paperless das Panel erreicht, z.B. http://panel:8300
  REDO_SECRET     das Geheimnis, das der Webhook mitsendet (im Panel dieselbe Variable)
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("PAPERLESS_API", "http://localhost:8000/api").rstrip("/")
TOK = os.environ["PAPERLESS_TOKEN"]
PANEL_URL = os.environ.get("PANEL_URL", "http://panel:8300").rstrip("/")
SECRET = os.environ["REDO_SECRET"]
CONFIG = os.environ.get("CLASSIFY_CONFIG", "/scripts/classify-config.json")
TAG_NAME = os.environ.get("REDO_TAG", "KI-neu")
FELD_NAME = os.environ.get("HINWEIS_FELD", "KI-Hinweis")
WF_NAME = os.environ.get("WORKFLOW_NAME", "paperlaiss — Vorschlag anfordern")


def ruf(pfad, daten=None, methode="GET"):
    req = urllib.request.Request(
        API + pfad,
        data=json.dumps(daten).encode() if daten is not None else None,
        headers={"Authorization": f"Token {TOK}", "Content-Type": "application/json"},
        method=methode)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r) if r.status != 204 else {}


def hole_oder_lege_an(pfad, name, felder):
    for e in ruf(f"{pfad}?page_size=1000")["results"]:
        if e["name"].strip().lower() == name.strip().lower():
            print(f"  {pfad.strip('/'):15} '{name}' vorhanden (id {e['id']})")
            return e["id"]
    neu = ruf(pfad, {"name": name, **felder}, "POST")
    print(f"  {pfad.strip('/'):15} '{name}' ANGELEGT (id {neu['id']})")
    return neu["id"]


def main():
    print("Vorschlagsmodus einrichten")
    tag_id = hole_oder_lege_an("/tags/", TAG_NAME, {"color": "#a020f0", "matching_algorithm": 0})
    feld_id = hole_oder_lege_an("/custom_fields/", FELD_NAME, {"data_type": "string"})

    # Der Workflow: zwei Auslöser, damit BEIDE Wege funktionieren — Tag dranhängen ODER
    # nur einen Hinweis eintippen. Ohne den zweiten müsste man immer auch den Tag setzen.
    wunsch = {
        "name": WF_NAME,
        "order": 10,
        "enabled": True,
        "triggers": [
            {"type": 3, "filter_has_tags": [tag_id]},
            {"type": 3, "filter_custom_field_query": json.dumps([feld_id, "exists", True])},
        ],
        "actions": [{
            "type": 4,
            "webhook": {
                "url": f"{PANEL_URL}/redo",
                # use_params statt body: sonst sendet Paperless den gerenderten String als
                # JSON-WERT, und der Empfänger muss zweimal auspacken.
                "use_params": True,
                # Gueltige Platzhalter sind ausschliesslich {{doc_url}} und {{doc_id}}
                # (documents/templating/workflows.py). Ein unbekannter Name — etwa doc_pk —
                # loest still zu NICHTS auf: der Webhook feuert, kommt aber leer an.
                "params": {"doc_id": "{{doc_id}}"},
                "headers": {"X-Redo-Secret": SECRET},
                "include_document": False,
            },
        }],
    }
    vorhanden = next((w for w in ruf("/workflows/?page_size=200")["results"]
                      if w["name"] == WF_NAME), None)
    if vorhanden:
        ruf(f"/workflows/{vorhanden['id']}/", wunsch, "PUT")
        print(f"  workflows       '{WF_NAME}' aktualisiert (id {vorhanden['id']})")
    else:
        neu = ruf("/workflows/", wunsch, "POST")
        print(f"  workflows       '{WF_NAME}' ANGELEGT (id {neu['id']})")

    try:
        cfg = json.load(open(CONFIG, encoding="utf-8"))
    except FileNotFoundError:
        cfg = {}
    cfg["redo_tag"] = TAG_NAME
    cfg["hinweis_field"] = FELD_NAME
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"  config          redo_tag='{TAG_NAME}', hinweis_field='{FELD_NAME}' in {CONFIG}")
    print("\nFertig. Tag an ein Dokument hängen oder einen Hinweis eintragen —")
    print("der Vorschlag erscheint im Panel unter „Vorschläge\".")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        sys.exit(f"Fehler {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
