#!/usr/bin/env python3
"""Fachtest: deploy/eingang/eingang.py — Eingangsordner nach Paperless (ohne Netz, mit Attrappe)."""
import datetime, json, os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy" / "eingang")); sys.path.insert(0, str(ROOT / "tests"))
import eingang as eg  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — Eingang")
w = Path(tempfile.mkdtemp())
for n in ("a.pdf", ".versteckt.pdf", "~$sperr.docx", "halb.pdf.part", "_Fehler/alt.pdf", "unter/b.jpg",
          "a.pdf.fehler.txt"):
    (w / n).parent.mkdir(parents=True, exist_ok=True); (w / n).write_bytes(b"x")
r.check("Kandidaten: ohne versteckte, Sperr-, Temp-Dateien, _Fehler/ und Fehlernotizen, mit Unterordnern",
        sorted(p.relative_to(w).as_posix() for p in eg.kandidaten(w)) == ["a.pdf", "unter/b.jpg"])
st = (w / "a.pdf").stat()
r.check("Bereit: erst nach Ruhezeit und gleicher Größe in zwei Runden",
        not eg.bereit(st, None, st.st_mtime + 60, 30) and not eg.bereit(st, st.st_size, st.st_mtime + 5, 30)
        and eg.bereit(st, st.st_size, st.st_mtime + 60, 30))
r.check("Auswerten: läuft, ok, Dublette (auch result_data.duplicate_of), Fehler",
        eg.auswerten({"status": "STARTED"}) == "laeuft" and eg.auswerten({"status": "SUCCESS"}) == "ok"
        and eg.auswerten({"status": "FAILURE", "result": "Not consuming x: It is a duplicate of y"}) == "dublette"
        and eg.auswerten({"status": "failure", "result": "x", "result_data": {"duplicate_of": 7}}) == "dublette"
        and eg.auswerten({"status": "FAILURE", "result": "Unsupported mime type"}) == ("fehler", "Unsupported mime type"))

# Archive name: date in front of the ORIGINAL name, counter on a clash, subfolders kept.
a = Path(tempfile.mkdtemp())
tag = datetime.datetime(2026, 11, 14, 0, 30)
r.check("Archivname: „YYYY.MM.DD <Originalname>“", eg.archiv_ziel(a, Path("Scan 7.pdf"), tag) == a / "2026.11.14 Scan 7.pdf")
(a / "2026.11.14 Scan 7.pdf").write_bytes(b"1"); (a / "2026.11.14 Scan 7 (2).pdf").write_bytes(b"2")
r.check("Archivname: belegt → Zähler (3) vor der Endung",
        eg.archiv_ziel(a, Path("Scan 7.pdf"), tag) == a / "2026.11.14 Scan 7 (3).pdf")
r.check("Archivname: Unterordner bleibt, Datei ohne Endung geht auch",
        eg.archiv_ziel(a, Path("Steuer/README"), tag) == a / "Steuer" / "2026.11.14 README")
# 2026-11-13 23:30 UTC is already the 14th in Berlin: the date is the day of the import in the configured zone.
utc_spaet = datetime.datetime(2026, 11, 13, 23, 30, tzinfo=datetime.timezone.utc).timestamp()
r.check("Importtag in Europe/Berlin, nicht UTC", eg.importtag(utc_spaet, eg.zone("Europe/Berlin")).date()
        == datetime.date(2026, 11, 14))


class Attrappe:
    def __init__(self, ergebnis): self.ergebnis, self.hoch, self.tags = ergebnis, [], []
    def hochladen(self, pfad, tags=()): self.hoch.append(pfad.name); self.tags.append(list(tags)); return f"t-{pfad.name}"
    def task(self, tid): return self.ergebnis(tid)


def durchlauf(ergebnis, konto=None, cfg=None, unter="brief.pdf"):
    w = Path(tempfile.mkdtemp())
    eingang = w / ((konto or {}).get("eingang") or (cfg or {}).get("eingang") or "")
    (eingang / unter).parent.mkdir(parents=True, exist_ok=True); (eingang / unter).write_bytes(b"pdf")
    k = [{"name": "anna", "ordner": str(w), **(konto or {})}]; api = Attrappe(ergebnis); z, g = {}, {}
    alt = time.time() + 100
    e = []
    for _ in range(3):                                      # Größe merken, hochladen, Task auswerten
        e += eg.runde(k, {"anna": api}, z, g, alt, 30, cfg)
    return w, api, e, z


w1, a1, e1, _ = durchlauf(lambda tid: {"status": "SUCCESS"})
r.check("Ohne Archiv: einmal hochgeladen, nach Erfolg aus dem Ordner entfernt",
        a1.hoch == ["brief.pdf"] and not (w1 / "brief.pdf").exists() and ("anna", "brief.pdf", "ok") in e1, str(e1))
w2, a2, e2, _ = durchlauf(lambda tid: {"status": "FAILURE", "result": "It is a duplicate of 12"})
r.check("Ohne Archiv: Dublette wird entfernt (schon in Paperless)", not (w2 / "brief.pdf").exists())
w3, a3, e3, _ = durchlauf(lambda tid: {"status": "FAILURE", "result": "kaputt"})
r.check("Ohne Archiv: Fehler → _Fehler/ mit Grund als Textdatei, nicht gelöscht",
        not (w3 / "brief.pdf").exists() and (w3 / "_Fehler/brief.pdf").exists()
        and "kaputt" in (w3 / "_Fehler/brief.pdf.txt").read_text(encoding="utf-8"))
w4, a4, e4, _ = durchlauf(lambda tid: {"status": "STARTED"})
r.check("Solange der Task läuft, bleibt die Datei und wird nicht erneut hochgeladen",
        (w4 / "brief.pdf").exists() and a4.hoch == ["brief.pdf"])

INBOX = {"eingang": "Inbox", "archiv": "Archiv"}
heute = eg.importtag(time.time() + 100, eg.zone("Europe/Berlin")).strftime("%Y.%m.%d")
w5, a5, e5, z5 = durchlauf(lambda tid: {"status": "SUCCESS"}, cfg=INBOX)
r.check("Inbox/Archiv: nach dem Konsum nach Archiv/„<Datum> <Originalname>“, aus Inbox weg",
        not (w5 / "Inbox/brief.pdf").exists() and (w5 / f"Archiv/{heute} brief.pdf").read_bytes() == b"pdf"
        and z5["anna"] == {}, str(e5))
w6, a6, e6, _ = durchlauf(lambda tid: {"status": "FAILURE", "result": "Not consuming: It is a duplicate of 9"},
                          konto=INBOX)
r.check("Inbox/Archiv (am Konto eingestellt): Dublette gilt als konsumiert → Archiv",
        (w6 / f"Archiv/{heute} brief.pdf").exists() and not (w6 / "Inbox/brief.pdf").exists())
w7, a7, e7, z7 = durchlauf(lambda tid: {"status": "FAILURE", "result": "Unsupported mime type"}, cfg=INBOX)
notiz = w7 / "Inbox/brief.pdf.fehler.txt"
r.check("Inbox/Archiv: Fehlschlag bleibt in Inbox, Notiz mit Grund daneben, nichts im Archiv",
        (w7 / "Inbox/brief.pdf").exists() and "Unsupported mime type" in notiz.read_text(encoding="utf-8")
        and not (w7 / "Archiv").exists())
k7 = [{"name": "anna", "ordner": str(w7)}]
for _ in range(3):
    eg.runde(k7, {"anna": a7}, z7, {}, time.time() + 100, 30, INBOX)
r.check("Inbox/Archiv: unveränderte Fehldatei wird nicht wieder und wieder hochgeladen", a7.hoch == ["brief.pdf"])
notiz.unlink()
g7 = {}
for _ in range(2):
    eg.runde(k7, {"anna": a7}, z7, g7, time.time() + 100, 30, INBOX)
r.check("Inbox/Archiv: Notiz gelöscht → neuer Versuch", a7.hoch == ["brief.pdf", "brief.pdf"], str(a7.hoch))
w8, a8, _, _ = durchlauf(lambda tid: {"status": "SUCCESS"}, cfg=INBOX, unter="Steuer 2025/beleg.pdf")
r.check("Inbox/Archiv: Unterordner der Inbox bleibt im Archiv erhalten",
        (w8 / f"Archiv/Steuer 2025/{heute} beleg.pdf").exists())
w9 = Path(tempfile.mkdtemp()); (w9 / "Archiv").mkdir(); (w9 / "Archiv/alt.pdf").write_bytes(b"a")
(w9 / "neu.pdf").write_bytes(b"n")
a9, z9, g9 = Attrappe(lambda tid: {"status": "SUCCESS"}), {}, {}
for _ in range(3):
    eg.runde([{"name": "anna", "ordner": str(w9)}], {"anna": a9}, z9, g9, time.time() + 100, 30, {"archiv": "Archiv"})
r.check("Inbox = Wurzel: das Archiv wird nie erneut importiert (die neue Datei schon)", a9.hoch == ["neu.pdf"], str(a9.hoch))
w10, a10, _, _ = durchlauf(lambda tid: {"status": "SUCCESS"}, konto={"tags": ["Martin", 7]})
r.check("Tags je Konto gehen mit dem Upload", a10.tags == [["Martin", 7]])
z_alt = {"anna": {"/x/weg.pdf": "t-alt"}}
eg.runde([{"name": "anna", "ordner": str(Path(tempfile.mkdtemp()))}], {"anna": Attrappe(lambda t: {"status": "SUCCESS"})},
         z_alt, {}, time.time(), 30, INBOX)
r.check("Zustand von 0.9 (Task-ID als Text) wird gelesen und abgeschlossen", z_alt == {"anna": {}})


class TagApi(eg.Api):
    def __init__(self): super().__init__("http://x/api", "t"); self.rufe = []
    def _req(self, pfad, *a, **k):
        self.rufe.append(pfad)
        return {"results": [{"id": 140, "name": "Martin"}] if "Martin" in pfad else []}


ta = TagApi()
r.check("Tag-Namen → IDs (je Name einmal gefragt), Zahlen bleiben, Unbekanntes fällt weg",
        ta.tag_ids(["Martin", "12", "Gibtsnicht"]) == [140, 12] and ta.tag_ids(["Martin"]) == [140]
        and len(ta.rufe) == 2, str(ta.rufe))
sys.exit(r.done())
