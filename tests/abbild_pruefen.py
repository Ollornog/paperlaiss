#!/usr/bin/env python3
"""The panel routes of "Prüfen" and the "Nacharbeit" comparison, end to end — runs IN the built panel image.

The stdlib suite cannot import `app.py` (FastAPI). Here the real app runs against a stand-in for Paperless (a small
HTTP server in this process) and the real `classify.py` (for the effective config):

    docker build -t paperlaiss-panel:ci ./panel
    docker run --rm -v "$PWD/tests:/tests:ro" -v "$PWD/classify.py:/src/classify.py:ro" \\
        paperlaiss-panel:ci python /tests/abbild_pruefen.py

Checked (T-9 items 1, 7, 8): flagged documents come with the reasons of their trace; probably own identifiers are
proposed, taking one over writes `eigene_kennungen` and clears it from every correspondent in the store, "räumen"
only clears, "nicht eigene" hides the proposal; every route needs the panel token; a bulk change without a history
entry shows up in "Nacharbeit" as a correction "ohne Protokoll".
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from _kit.report import Report  # noqa: E402

r = Report("Abbild — Prüfen und Nacharbeit im Panel (T-9)")

TAGS = [{"id": 5, "name": "KI-unsicher"}, {"id": 6, "name": "Kaputt"}, {"id": 7, "name": "Steuer"}]
DOKS = {11: {"id": 11, "title": "Lohnabrechnung", "correspondent": 3, "document_type": 2, "tags": [5],
             "created": "2026-03-31"},
        12: {"id": 12, "title": "Scan", "correspondent": None, "document_type": None, "tags": [6], "created": "2026-01-02"},
        13: {"id": 13, "title": "Brief", "correspondent": 4, "document_type": 2, "tags": [7], "created": "2026-02-01"}}
KORR = [{"id": 3, "name": "Muster GmbH"}, {"id": 4, "name": "Beispiel AG"}]
TYPEN = [{"id": 2, "name": "Brief"}]
GESEHEN = []


class Paperless(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        GESEHEN.append(self.path)
        p = u.path.removeprefix("/api")
        if p == "/tags/":
            daten = {"results": TAGS, "next": None}
        elif p == "/correspondents/":
            daten = {"results": KORR, "next": None}
        elif p == "/document_types/":
            daten = {"results": TYPEN, "next": None}
        elif p == "/documents/" and "tags__id__in" in q:
            ids = {int(x) for x in q["tags__id__in"][0].split(",")}
            daten = {"results": [d for d in DOKS.values() if ids & set(d["tags"])], "next": None}
        elif p == "/documents/" and "id__in" in q:
            ids = {int(x) for x in q["id__in"][0].split(",")}
            daten = {"results": [d for i, d in DOKS.items() if i in ids], "next": None}
        elif p.startswith("/documents/") and p.endswith("/history/"):
            daten = []
        else:
            self.send_response(404); self.end_headers(); return
        roh = json.dumps(daten).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)


server = ThreadingHTTPServer(("127.0.0.1", 0), Paperless)
threading.Thread(target=server.serve_forever, daemon=True).start()

tmp = Path(tempfile.mkdtemp())
(tmp / "traces").mkdir()
shutil.copy(os.environ.get("CLASSIFY_SRC", "/src/classify.py"), tmp / "classify.py")
EIGEN_IBAN = "DE02 1203 0000 0000 2020 51"
(tmp / "classify-config.json").write_text(json.dumps({
    "unsicher_tag": "KI-unsicher", "kaputt_tag": "Kaputt", "eigene_kennungen": {"iban": [EIGEN_IBAN]}}), encoding="utf-8")
(tmp / "correspondents.json").write_text(json.dumps({
    "3": {"iban": [EIGEN_IBAN, "DE89 3704 0044 0532 0130 00"], "aliase": ["Muster"],
          "erfasst": {"iban": {EIGEN_IBAN: "KI", "DE89 3704 0044 0532 0130 00": "KI"}}},
    "4": {"telefon": ["+4930123456"], "erfasst": {"telefon": {"+4930123456": "KI · Dokument 9"}}}}), encoding="utf-8")
(tmp / "eigene_vorschlaege.json").write_text(json.dumps({
    "telefon:+4930123456": {"feld": "telefon", "wert": "+4930123456", "korrespondenten": 4, "dokumente": [11, 13],
                            "zuletzt": "2026-11-19"},
    "iban:AT611904300234573201": {"feld": "iban", "wert": "AT611904300234573201", "korrespondenten": 3,
                                  "dokumente": [13]}}), encoding="utf-8")
(tmp / "traces" / "11.json").write_text(json.dumps({
    "id": 11, "ts_utc": "2026-11-18T10:00:00+00:00", "_stage": "fertig",
    "pruefen": {"eigene_person": "Korrespondent ist eine eigene Person"},
    "writeback": {"ergebnis": {"correspondent": 4, "document_type": 2, "created": "2026-03-31", "title": "Lohnabrechnung"},
                  "fields_ki": {}}}), encoding="utf-8")

os.environ.update({"CLASSIFY_DIR": str(tmp), "PAPERLESS_API": f"http://127.0.0.1:{server.server_port}/api",
                   "PAPERLESS_TOKEN": "x", "PANEL_TOKEN": "geheim-fuer-den-test", "PANEL_NACHARBEIT_INTERVALL_S": "0"})
for kandidat in (HIER.parent / "panel", Path("/app")):
    if (kandidat / "app.py").is_file():
        sys.path.insert(0, str(kandidat))
        break
try:
    import app as panel
    from fastapi.testclient import TestClient
except ImportError as e:
    r.check("Panel und TestClient importierbar", False, repr(e))
    sys.exit(r.done())

c = TestClient(panel.app)
K = {"Authorization": "Bearer geheim-fuer-den-test"}

r.check("Prüfen: ohne Token keine Daten", c.get("/api/pruefen").status_code == 401
        and c.post("/api/pruefen/kennung", json={}).status_code == 401 and c.get("/pruefen").status_code == 401)
r.check("Prüfen: die Seite ist da und nennt beide Abschnitte",
        (lambda t: "Markierte Dokumente" in t and "Wahrscheinlich eigene Kennungen" in t)(c.get("/pruefen", headers=K).text))

d = c.get("/api/pruefen", headers=K).json()
doks = {z["doc"]: z for z in d["dokumente"]}
r.check("Prüfen: die Dokumente mit Prüf-Tag oder Kaputt-Tag, nicht die übrigen",
        set(doks) == {11, 12} and set(d["tags"]) == {"Kaputt", "KI-unsicher"}, json.dumps(d)[:400])
r.check("Prüfen: der Grund kommt aus dem Trace, mit Korrespondent und Typ",
        doks.get(11, {}).get("gruende") == [{"art": "eigene_person", "text": "Korrespondent ist eine eigene Person"}]
        and doks[11]["korrespondent"] == "Muster GmbH" and doks[11]["typ"] == "Brief")
r.check("Prüfen: ohne Trace steht das ausdrücklich da", "kein Grund im Trace" in doks.get(12, {}).get("gruende", [{}])[0].get("text", ""))
kenn = {(k["feld"], k["wert"]): k for k in d["kennungen"]}
r.check("Kennungen: der Vorschlag nennt, wo der Wert in den Stammdaten steht",
        kenn.get(("telefon", "+4930123456"), {}).get("bei") == ["4"] and not kenn[("telefon", "+4930123456")]["schon_eigen"],
        json.dumps(d["kennungen"])[:400])
r.check("Kennungen: eine eigene IBAN, die noch in den Stammdaten steht, wird zum Räumen angeboten",
        kenn.get(("iban", EIGEN_IBAN), {}).get("schon_eigen") is True and kenn[("iban", EIGEN_IBAN)]["bei"] == ["3"])

a = c.post("/api/pruefen/kennung", headers=K, json={"feld": "telefon", "wert": "+4930123456", "aktion": "uebernehmen"}).json()
cfg = json.loads((tmp / "classify-config.json").read_text(encoding="utf-8"))
store = json.loads((tmp / "correspondents.json").read_text(encoding="utf-8"))
vor = json.loads((tmp / "eigene_vorschlaege.json").read_text(encoding="utf-8"))
r.check("Übernehmen: steht danach in eigene_kennungen, die IBAN bleibt",
        cfg["eigene_kennungen"].get("telefon") == ["+4930123456"] and cfg["eigene_kennungen"]["iban"] == [EIGEN_IBAN], str(cfg))
r.check("Übernehmen: aus den Stammdaten aller Korrespondenten entfernt, samt Herkunft",
        a.get("aus_stammdaten") == ["4"] and "telefon" not in store["4"] and "erfasst" not in store["4"], str(store["4"]))
r.check("Übernehmen: der Vorschlag ist erledigt", "telefon:+4930123456" not in vor)

a = c.post("/api/pruefen/kennung", headers=K, json={"feld": "iban", "wert": EIGEN_IBAN, "aktion": "raeumen"}).json()
store = json.loads((tmp / "correspondents.json").read_text(encoding="utf-8"))
cfg2 = json.loads((tmp / "classify-config.json").read_text(encoding="utf-8"))
r.check("Räumen: nur die eigene IBAN geht, die fremde bleibt; Aliase bleiben; Config unverändert",
        store["3"]["iban"] == ["DE89 3704 0044 0532 0130 00"] and store["3"]["aliase"] == ["Muster"]
        and list(store["3"]["erfasst"]["iban"]) == ["DE89 3704 0044 0532 0130 00"] and cfg2 == cfg, str(store["3"]))

c.post("/api/pruefen/kennung", headers=K, json={"feld": "iban", "wert": "AT61 1904 3002 3457 3201", "aktion": "verwerfen"})
vor = json.loads((tmp / "eigene_vorschlaege.json").read_text(encoding="utf-8"))
d2 = c.get("/api/pruefen", headers=K).json()
r.check("Nicht eigene: der Vorschlag bleibt gespeichert, wird aber nicht mehr gezeigt",
        vor.get("iban:AT611904300234573201", {}).get("verworfen") is True
        and not [k for k in d2["kennungen"] if k["feld"] == "iban" and "AT61" in k["wert"].replace(" ", "")], str(d2["kennungen"]))
r.check("Unsinn wird abgewiesen", c.post("/api/pruefen/kennung", headers=K,
                                         json={"feld": "passwort", "wert": "x", "aktion": "uebernehmen"}).status_code == 400)

# Nacharbeit: the run left correspondent 4, the document now has 3 — and the history is empty (bulk edit).
r.check("Nacharbeit: Abgleich startet", panel._nacharbeit_anstossen() is True)
for _ in range(100):
    if not panel._NA["laeuft"]:
        break
    time.sleep(0.1)
na = json.loads((tmp / "nacharbeit.json").read_text(encoding="utf-8")) if (tmp / "nacharbeit.json").exists() else {}
lauf = next(iter((na.get("laeufe") or {}).values()), {})
r.check("Nacharbeit: eine Massenänderung ohne Historie zählt als Korrektur „ohne Protokoll“",
        [(k["feld"], k["ki"], k["neu"], k["wer"]) for k in lauf.get("korrekturen", [])]
        == [("Korrespondent", "Beispiel AG", "Muster GmbH", "ohne Protokoll")], json.dumps(na)[:500] + str(panel._NA))
r.check("Nacharbeit: der Takt ist mit 0 abgeschaltet", panel._nacharbeit_takt_starten() is False)
_runden = []
panel._nacharbeit_takt(7, warten=_runden.append, runden=2)
r.check("Nacharbeit: der Takt wartet das Intervall und stößt dann den Abgleich an", _runden == [7, 7])

server.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(r.done())
