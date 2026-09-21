#!/usr/bin/env python3
"""Beispiel für `nachbearbeitung` — läuft nach jedem Writeback des Klassifizierers.

Wofür die Naht gedacht ist: alles, was zu EINER Installation gehört und deshalb nicht in einen
mandantenneutralen Klassifizierer gehört — eine Verknüpfung in ein Fremdsystem, hauseigene
Regeln, eine Meldung an einen Chat. Ohne sie müsste man paperlaiss forken, und genau daraus
entstehen auseinanderlaufende Stände desselben Codes.

Einrichten: in `classify-config.json` den Pfad eintragen —
    "nachbearbeitung": "/scripts/meine-nachbearbeitung.py"

Das Skript bekommt auf stdin:
    {"doc_id": 915, "erfolg": true, "patch": {…}, "lesbar": {…},
     "quelle": "redo|manual|bulk|auto", "dry": false, "vorschlag": false}

Es läuft mit denselben Umgebungsvariablen wie der Klassifizierer (PAPERLESS_API,
PAPERLESS_TOKEN …), kann also selbst die API benutzen. Was es ausgibt, landet im Log.

Es darf scheitern: ein Fehler wird protokolliert, beendet aber nicht den Lauf. Die
Klassifizierung ist zu diesem Zeitpunkt bereits geschrieben, und eine Zusatzaufgabe darf kein
Dokument unklassifiziert zurücklassen.
"""
import json
import os
import sys

daten = json.load(sys.stdin)

doc_id = daten["doc_id"]
erfolg = daten["erfolg"]
lesbar = daten.get("lesbar") or {}

# Ein Vorschlag wurde noch nicht geschrieben — hier gibt es nichts nachzubereiten.
if daten.get("vorschlag"):
    sys.exit(0)

if not erfolg:
    print(f"Writeback für {doc_id} schlug fehl — nichts nachzubereiten")
    sys.exit(0)

# --- ab hier die eigene Logik -------------------------------------------------
# Beispiel: nur melden, was der Klassifizierer entschieden hat.
korrespondent = lesbar.get("correspondent") or lesbar.get("korrespondent") or "?"
typ = lesbar.get("document_type") or lesbar.get("dokumenttyp") or "?"
print(f"Dokument {doc_id}: {typ} von {korrespondent}")

# Ein echtes Beispiel wäre: eine Verknüpfung in einem Fremdsystem setzen.
#
#   import urllib.request
#   req = urllib.request.Request(
#       os.environ["FREMDSYSTEM_API"] + "/belege/",
#       data=json.dumps({"paperless_id": doc_id, "typ": typ}).encode(),
#       headers={"Authorization": "Bearer " + os.environ["FREMDSYSTEM_TOKEN"],
#                "Content-Type": "application/json"}, method="POST")
#   urllib.request.urlopen(req, timeout=20)
#
# Wichtig: zeitlich begrenzen (der Aufrufer bricht nach 120 s ab) und Fehler selbst
# behandeln, wenn ein Fehlschlag folgenlos bleiben soll.
