#!/usr/bin/env python3
"""Fachtest: deploy/vorab/ausrichtung.py — the decision whether a scanned page lies upside down (T-8).

Rendering, Tesseract and qpdf run in the Paperless image (`tests/abbild_ausrichtung.py`); here the pure parts: reading
Tesseract's TSV, the decision rule, the 180° turn of a raster, the language choice, the switch in the config.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from _kit.report import Report  # noqa: E402

spec = importlib.util.spec_from_file_location("ausrichtung", ROOT / "deploy" / "vorab" / "ausrichtung.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

r = Report("Fachtest — deploy/vorab/ausrichtung.py")

KOPF = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def tsv(*woerter):
    """TSV lines: (text, conf, width, height)."""
    return "\n".join([KOPF] + [f"5\t1\t1\t1\t1\t{i}\t10\t10\t{b}\t{h}\t{k}\t{t}" for i, (t, k, b, h) in enumerate(woerter)])


r.check("TSV: nur Wörter ab Konfidenz 75 mit drei Zeichen zählen",
        A.gute_woerter(tsv(("Abrechnung", 96, 80, 12), ("der", 80, 20, 12), ("ab", 99, 15, 12), ("Strom", 60, 40, 12),
                           ("—.,", 90, 20, 12), ("2025", 91, 30, 12)) + "\n4\t1\t1\t1\t1\t0\t0\t0\t9\t9\t-1\t")
        == (3, 0))
r.check("TSV: kaputte Zeilen stören nicht", A.gute_woerter("x\n5\t1\tkaputt\n5\t1\t1\t1\t1\t1\t1\t1\ta\tb\tc\tWort") == (0, 0))
r.check("TSV: höhere als breite Wortkästen zählen als quer", A.gute_woerter(tsv(("Rechnung", 95, 12, 80))) == (1, 1))

r.check("Regel: gedreht klar besser → drehen", A.gedreht_besser(13, 91) and A.gedreht_besser(0, 12))
r.check("Regel: zu wenig gute Wörter gedreht → nicht drehen", not A.gedreht_besser(0, 11))
r.check("Regel: nur etwas besser → nicht drehen (Zweifel)", not A.gedreht_besser(20, 50))

# A page as raster: the bytes reversed are the page turned by 180°.
W, H = 4, 3
PIX = bytes(range(0, 240, 20))
gelesen = []


def lesen_attrappe(ergebnisse):
    folge = list(ergebnisse)

    def lesen(pfad, sprache):
        gelesen.append((Path(pfad).read_bytes(), sprache))
        return folge.pop(0)
    return lesen


with tempfile.TemporaryDirectory() as tmp:
    gelesen.clear()
    ja, grund = A.seite_pruefen(W, H, PIX, "deu", tmp, lesen_attrappe([(13, 0), (91, 0)]))
    r.check("Seite: kopfüber erkannt, mit Zahlen im Grund", ja and grund == "kopfüber (13 Wörter, gedreht 91)", grund)
    r.check("Seite: zuerst wie sie ist, dann als Raster rückwärts (= 180°) gelesen, mit der Sprache",
            [g[0] for g in gelesen] == [A.pgm(W, H, PIX), A.pgm(W, H, PIX[::-1])] and {g[1] for g in gelesen} == {"deu"})
    gelesen.clear()
    ja, grund = A.seite_pruefen(W, H, PIX, "deu", tmp, lesen_attrappe([(55, 0)]))
    r.check("Seite: gut lesbar → kein zweites Lesen", not ja and len(gelesen) == 1 and grund.startswith("aufrecht"))
    ja, grund = A.seite_pruefen(W, H, PIX, "deu", tmp, lesen_attrappe([(10, 8), (90, 80)]))
    r.check("Seite: liegt quer → bleibt für Paperless", not ja and "quer" in grund, grund)
    ja, grund = A.seite_pruefen(W, H, PIX, "deu", tmp, lesen_attrappe([(10, 0), (90, 80)]))
    r.check("Seite: gedreht quer gelesen → bleibt", not ja and "quer" in grund, grund)
    gelesen.clear()
    ja, grund = A.seite_pruefen(W, H, bytes([255] * 12), "deu", tmp, lesen_attrappe([]))
    r.check("Seite: kein Bild (Raster weiß) → nicht gelesen", not ja and grund == "kein Scan" and not gelesen)

r.check("Sprachen: aus PAPERLESS_OCR_LANGUAGE, soweit installiert",
        A.sprachen({"PAPERLESS_OCR_LANGUAGE": "deu+fra+xyz"}, ["deu", "eng", "fra", "osd"]) == "deu+fra")
r.check("Sprachen: ohne Einstellung alle außer osd",
        A.sprachen({}, ["deu", "eng", "osd"]) == "deu+eng" and A.sprachen({"PAPERLESS_OCR_LANGUAGE": "xyz"}, ["eng", "osd"]) == "eng")

with tempfile.TemporaryDirectory() as tmp:
    r.check("Schalter: ohne Config an", A.einstellung(tmp) is True)
    Path(tmp, "classify-config.json").write_text(json.dumps({"kopfueber_drehen": False}))
    r.check("Schalter: kopfueber_drehen false → aus", A.einstellung(tmp) is False)
    Path(tmp, "classify-config.json").write_text("{kaputt")
    r.check("Schalter: kaputte Config → an (wie leerseiten)", A.einstellung(tmp) is True)

r.check("vorab.py ruft den Schritt nach den leeren Seiten auf",
        "ausrichtung.py" in (ROOT / "deploy/vorab/vorab.py").read_text(encoding="utf-8")
        and __import__("re").search(r'SCHRITTE = \("mailbilder.py", "leerseiten.py", "ausrichtung.py"\)',
                                    (ROOT / "deploy/vorab/vorab.py").read_text(encoding="utf-8")) is not None)
sys.exit(r.done())
