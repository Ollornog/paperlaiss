#!/usr/bin/env python3
"""Fachtest: deploy/eingang/eingang.py — Eingangsordner nach Paperless (ohne Netz, mit Attrappe)."""
import os, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy" / "eingang")); sys.path.insert(0, str(ROOT / "tests"))
import eingang as eg  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — Eingang")
w = Path(tempfile.mkdtemp())
for n in ("a.pdf", ".versteckt.pdf", "~$sperr.docx", "halb.pdf.part", "_Fehler/alt.pdf", "unter/b.jpg"):
    (w / n).parent.mkdir(parents=True, exist_ok=True); (w / n).write_bytes(b"x")
r.check("Kandidaten: ohne versteckte, Sperr-, Temp-Dateien und _Fehler/, mit Unterordnern",
        sorted(p.relative_to(w).as_posix() for p in eg.kandidaten(w)) == ["a.pdf", "unter/b.jpg"])
st = (w / "a.pdf").stat()
r.check("Bereit: erst nach Ruhezeit und gleicher Größe in zwei Runden",
        not eg.bereit(st, None, st.st_mtime + 60, 30) and not eg.bereit(st, st.st_size, st.st_mtime + 5, 30)
        and eg.bereit(st, st.st_size, st.st_mtime + 60, 30))
r.check("Auswerten: läuft, ok, Dublette, Fehler",
        eg.auswerten({"status": "STARTED"}) == "laeuft" and eg.auswerten({"status": "SUCCESS"}) == "ok"
        and eg.auswerten({"status": "FAILURE", "result": "Not consuming x: It is a duplicate of y"}) == "dublette"
        and eg.auswerten({"status": "FAILURE", "result": "Unsupported mime type"}) == ("fehler", "Unsupported mime type"))


class Attrappe:
    def __init__(self, ergebnis): self.ergebnis, self.hoch = ergebnis, []
    def hochladen(self, pfad): self.hoch.append(pfad.name); return f"t-{pfad.name}"
    def task(self, tid): return self.ergebnis(tid)


def durchlauf(ergebnis):
    w = Path(tempfile.mkdtemp()); (w / "brief.pdf").write_bytes(b"pdf")
    k = [{"name": "anna", "ordner": str(w)}]; api = Attrappe(ergebnis); z, g = {}, {}
    alt = time.time() + 100
    e1 = eg.runde(k, {"anna": api}, z, g, alt, 30)      # Größe merken
    e2 = eg.runde(k, {"anna": api}, z, g, alt, 30)      # hochladen
    e3 = eg.runde(k, {"anna": api}, z, g, alt, 30)      # Task auswerten
    return w, api, e1 + e2 + e3


w1, a1, e1 = durchlauf(lambda tid: {"status": "SUCCESS"})
r.check("Ablauf: einmal hochgeladen, nach Erfolg aus dem Ordner entfernt",
        a1.hoch == ["brief.pdf"] and not (w1 / "brief.pdf").exists() and ("anna", "brief.pdf", "ok") in e1, str(e1))
w2, a2, e2 = durchlauf(lambda tid: {"status": "FAILURE", "result": "It is a duplicate of 12"})
r.check("Ablauf: Dublette wird entfernt (schon in Paperless)", not (w2 / "brief.pdf").exists())
w3, a3, e3 = durchlauf(lambda tid: {"status": "FAILURE", "result": "kaputt"})
r.check("Ablauf: Fehler → _Fehler/ mit Grund als Textdatei, nicht gelöscht",
        not (w3 / "brief.pdf").exists() and (w3 / "_Fehler/brief.pdf").exists()
        and "kaputt" in (w3 / "_Fehler/brief.pdf.txt").read_text(encoding="utf-8"))
w4, a4, e4 = durchlauf(lambda tid: {"status": "STARTED"})
r.check("Ablauf: solange der Task läuft, bleibt die Datei und wird nicht erneut hochgeladen",
        (w4 / "brief.pdf").exists() and a4.hoch == ["brief.pdf"])
sys.exit(r.done())
