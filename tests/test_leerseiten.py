#!/usr/bin/env python3
"""Fachtest: deploy/vorab/leerseiten.py und vorab.py — komplett weiße Seiten, Einstieg der Vorab-Schritte.

Hier die reine Entscheidung (ist eine Seite leer?) an gebauten Rastern, der Schalter in der Config
und dass nichts einen Import aufhält. Das Rendern und Entfernen mit Ghostscript und qpdf prüft
`tests/abbild_leerseiten.py` im Paperless-Abbild, wo beides vorhanden ist. Stdlib-only.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from _kit.report import Report  # noqa: E402

VORAB = ROOT / "deploy" / "vorab"
spec = importlib.util.spec_from_file_location("leerseiten", VORAB / "leerseiten.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

r = Report("Fachtest — deploy/vorab/leerseiten.py (komplett weiße Seiten)")

W, H = 1240, 1754              # A4 bei 150 dpi


def raster(flecken=(), grau=255):
    """Weiße Seite mit Flecken [(x, y, breite, höhe, wert)] — 1 Punkt ≈ 0,17 mm."""
    px = bytearray([grau]) * (W * H)
    for x, y, b, h, wert in flecken:
        for yy in range(y, y + h):
            px[yy * W + x:yy * W + x + b] = bytes([wert]) * b
    return bytes(px)


def leer(flecken=(), grau=255):
    return L.seite_leer(W, H, raster(flecken, grau))


_staub = [(200 + 97 * i, 300 + 131 * i, 1 + i % 3, 1 + i % 2, 0) for i in range(12)]   # 12 Punkte, höchstens 0,5 mm
_faelle = [
    ("ganz weiß", leer(), True),
    ("nur Staub: 12 vereinzelte Punkte bis 0,5 mm", leer(_staub), True),
    ("Rand: Scannerkante innerhalb von 2 % zählt nicht", leer([(0, 0, 20, H, 0)]), True),
    ("Durchscheinendes (Grau 200, groß) zählt nicht als Tinte", leer([(300, 300, 400, 60, 200)]), True),
    ("Seitenzahl: ein Zeichen 1,7 mm hoch", leer([(620, 1600, 5, 10, 0)]), False),
    ("winzige Zählnummer: sechs Ziffern je 1,5 mm", leer([(100 + 7 * i, 1650, 4, 9, 30) for i in range(6)]), False),
    ("ein Haar: 1 Punkt breit, 2 mm lang", leer([(500, 500, 1, 12, 0)]), False),
    ("Staub plus ein einziges Zeichen", leer(_staub + [(900, 900, 6, 8, 0)]), False),
    ("mehr dunkle Punkte als je auf einer leeren Seite gemessen", leer([(100 + 3 * i, 400 + 3 * (i % 50), 1, 1, 0) for i in range(500)]), False),
    ("Schrift in mittlerem Grau (150) zählt als Tinte", leer([(620, 800, 12, 12, 150)]), False),
]
_falsch = [(n, e) for n, e, soll in _faelle if e[0] != soll]
r.check("Entscheidung: weiß und Staub fallen, jedes Zeichen, Haar oder Strich bleibt", not _falsch, str(_falsch))
# ---- T-13: punched holes. The back of a punched sheet from a duplex scan shows two dark discs of about 5.5 mm,
# 11 mm from the edge, 80 mm apart (DIN); measured: about 800 dark points each, the page stayed ("more than 400").
_MM = 150 / 25.4


def scheibe(cx_mm, cy_mm, d_mm=5.5, wert=0, ring=False):
    """A filled disc (or a ring of one point) as rows of runs, for `raster`."""
    r_, cx, cy, aus = d_mm * _MM / 2, cx_mm * _MM, cy_mm * _MM, []
    for yy in range(int(cy - r_), int(cy + r_) + 1):
        dy = yy - cy
        if abs(dy) > r_:
            continue
        hb = (r_ * r_ - dy * dy) ** 0.5
        x0, x1 = int(round(cx - hb)), int(round(cx + hb))
        if ring:            # a line of about 0.5 mm: points whose distance from the centre is r-3 … r
            aus += [(xx, yy, 1, 1, wert) for xx in range(x0, x1 + 1) if ((xx - cx) ** 2 + dy * dy) ** 0.5 >= r_ - 3]
        else:
            aus.append((x0, yy, x1 - x0 + 1, 1, wert))
    return aus


_rechts = scheibe(199, 108) + scheibe(199, 188)
_lochfaelle = [
    ("zwei Lochungen am rechten Rand (Rückseite)", leer(_rechts), True),
    ("zwei Lochungen am linken Rand, dazu Staub", leer(scheibe(11, 108) + scheibe(11, 188) + _staub), True),
    ("vier Lochungen (Vierfachlocher)", leer(scheibe(11, 40) + scheibe(11, 120) + scheibe(11, 200) + scheibe(11, 280)), True),
    ("Lochungen plus ein Zeichen", leer(_rechts + [(620, 1600, 5, 10, 0)]), False),
    ("runder Fleck in der Seitenmitte", leer(scheibe(105, 148)), False),
    ("fünf runde Flecken am Rand", leer(sum((scheibe(11, 30 + 50 * i) for i in range(5)), [])), False),
    ("Kreis (Ring) am Rand", leer(scheibe(199, 108, ring=True) + scheibe(199, 188, ring=True)), False),
    ("Balken 5 × 12 mm am Rand", leer([(1170, 600, 30, 71, 0)]), False),
    ("großer Kreis (12 mm) am Rand", leer(scheibe(199, 108, d_mm=12)), False),
    ("vom Einzug verzogene Lochungen (5,8 × 8,6 mm)", leer([(1160, 600, 34, 51, 0), (1160, 1070, 34, 51, 0)]), True),
    ("schmaler Strich 4 × 9 mm am Rand", leer([(1160, 600, 24, 53, 0)]), False),
]
_lochfalsch = [(n, e) for n, e, soll in _lochfaelle if e[0] != soll]
r.check("T-13 Lochung: gelochte leere Rückseiten fallen; Zeichen, Flecken in der Mitte, Ringe, Balken, fünf Flecken nicht",
        not _lochfalsch, str(_lochfalsch))
r.check("T-13 Lochung: der Grund nennt sie", "2 Lochung" in leer(_rechts)[1], leer(_rechts)[1])
r.check("Entscheidung: nennt den Grund", "mm" in leer([(620, 1600, 5, 10, 0)])[1] and "Staub" in leer(_staub)[1],
        f"{leer([(620, 1600, 5, 10, 0)])} {leer(_staub)}")
r.check("PGM: Kommentarzeile von Ghostscript wird übersprungen",
        L.pgm_lesen(b"P5\n# Image generated by Ghostscript\n3 2\n255\n" + bytes(6)) == (3, 2, bytes(6)))

# ---- Schalter in der Config
with tempfile.TemporaryDirectory() as _td:
    _alt = os.environ.pop("CLASSIFY_CONFIG", None)
    try:
        r.check("Schalter: ohne Config an", L.einstellung(_td) is True)
        Path(_td, "classify-config.json").write_text(json.dumps({"leerseiten_entfernen": False}))
        r.check("Schalter: leerseiten_entfernen false → aus", L.einstellung(_td) is False)
        Path(_td, "classify-config.json").write_text("{kaputt")
        r.check("Schalter: kaputte Config → an (Standard)", L.einstellung(_td) is True)
    finally:
        if _alt is not None:
            os.environ["CLASSIFY_CONFIG"] = _alt

# ---- Nie den Import aufhalten; nur PDFs
with tempfile.TemporaryDirectory() as _td:
    _eml = Path(_td, "mail.eml"); _eml.write_bytes(b"From: a@example.com\n\nText")
    _pdf = Path(_td, "kaputt.pdf"); _pdf.write_bytes(b"%PDF-1.7\nkein echtes PDF")
    _cfg = Path(_td, "aus.json"); _cfg.write_text(json.dumps({"leerseiten_entfernen": False}))

    def lauf(skript, pfad, **env):
        return subprocess.run([sys.executable, str(VORAB / skript)], capture_output=True, text=True, timeout=120,
                              env={**os.environ, "DOCUMENT_WORKING_PATH": str(pfad), **env})
    _a = lauf("leerseiten.py", _eml)
    r.check("Aufruf: eine .eml bleibt unberührt, Exit 0", _a.returncode == 0 and _eml.read_bytes().endswith(b"Text"))
    _b = lauf("leerseiten.py", _pdf, PATH="/nicht/da")      # ohne gs/qpdf: Fehler, aber Exit 0
    r.check("Aufruf: kaputtes PDF oder fehlende Programme halten den Import nicht auf (Exit 0, Datei gleich)",
            _b.returncode == 0 and _pdf.read_bytes() == b"%PDF-1.7\nkein echtes PDF" and "unverändert" in _b.stderr,
            _b.stderr[-300:])
    _c = lauf("leerseiten.py", _pdf, CLASSIFY_CONFIG=str(_cfg))
    r.check("Aufruf: ausgeschaltet → nichts passiert, keine Meldung", _c.returncode == 0 and "leerseiten" not in _c.stderr, _c.stderr)
    r.check("Aufruf: keine Hilfsdatei bleibt liegen", not list(Path(_td).glob("*.paperlaiss")))

    # vorab.py ruft beide Schritte; fehlt einer oder stürzt einer ab, läuft der Import trotzdem weiter.
    _v = lauf("vorab.py", _eml)
    r.check("Einstieg: vorab.py endet mit 0 und ruft die Schritte", _v.returncode == 0 and "mailbilder" in _v.stdout, _v.stdout[-300:] + _v.stderr[-300:])
    _kopie = Path(_td, "kopie"); _kopie.mkdir()
    (_kopie / "vorab.py").write_bytes((VORAB / "vorab.py").read_bytes())
    (_kopie / "leerseiten.py").write_text("raise SystemExit(7)\n")
    _v2 = subprocess.run([sys.executable, str(_kopie / "vorab.py")], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "DOCUMENT_WORKING_PATH": str(_eml)})
    r.check("Einstieg: fehlender Schritt (mailbilder) und Schritt mit Exit 7 → trotzdem Exit 0",
            _v2.returncode == 0 and "mailbilder.py fehlt" in _v2.stderr, _v2.stderr[-300:])
for _s in ("leerseiten.py", "vorab.py", "mailbilder.py"):
    r.check(f"{_s} ist ausführbar (Paperless ruft den Einstieg direkt auf)", os.access(VORAB / _s, os.X_OK))

sys.exit(r.done())
