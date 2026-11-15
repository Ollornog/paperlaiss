#!/usr/bin/env python3
"""OCR mode "scans" (T-19) on real originals: which file is a scan, which is digital.

The page check needs a PDF library, which the stdlib suite does not have. It runs where classify.py runs:

* in the Paperless image (post-consume run) with pikepdf, which comes with OCRmyPDF,
* in the panel image (manual runs, AI button) with pypdf, which comes with the export button.

  docker run --rm --entrypoint python3 -e CLASSIFY_PY=/src/classify.py -v "$PWD/tests:/tests:ro" \\
      -v "$PWD/classify.py:/src/classify.py:ro" ghcr.io/paperless-ngx/paperless-ngx:<version> /tests/abbild_ocr_art.py
  docker run --rm -e CLASSIFY_PY=/src/classify.py -v "$PWD/tests:/tests:ro" -v "$PWD/classify.py:/src/classify.py:ro" \\
      paperlaiss-panel:ci python /tests/abbild_ocr_art.py

With both libraries at hand (e.g. `uv run --with pikepdf --with pypdf`) both are measured and compared.
The originals in tests/fixtures/ocr-art/ were made with the real tools (erzeugen.sh): Ghostscript, img2pdf,
OCRmyPDF/Tesseract and qpdf.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from _kit.report import Report  # noqa: E402

os.environ.setdefault("CLASSIFY_LOG", str(Path(tempfile.mkdtemp(prefix="paperlaiss-ocrart-")) / "classify.log"))
QUELLE = Path(os.environ.get("CLASSIFY_PY") or HIER.parent / "classify.py")
spec = importlib.util.spec_from_file_location("classify", QUELLE)
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

MUSTER = HIER / "fixtures" / "ocr-art"
r = Report("Image test — OCR mode scans on real originals")


def lib(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


pikepdf, pypdf = lib("pikepdf"), lib("pypdf")
r.check("a PDF library is at hand (otherwise this test proves nothing)", bool(pikepdf or pypdf),
        f"pikepdf={bool(pikepdf)} pypdf={bool(pypdf)}")

ERWARTET = {
    # file: (mime, art, scan pages)
    "digital.pdf": ("application/pdf", "digital", []),
    "scan.pdf": ("application/pdf", "scan", [1]),
    "scan-ocr.pdf": ("application/pdf", "scan", [1]),       # invisible OCR layer (GlyphLessFont, render mode 3)
    "gemischt.pdf": ("application/pdf", "gemischt", [2]),   # digital, scan, digital
    "briefpapier.pdf": ("application/pdf", "digital", []),  # full-page image under visible text
    "foto.jpg": ("image/jpeg", "foto", None),
}

for datei, (mime, art, scan) in ERWARTET.items():
    daten = (MUSTER / datei).read_bytes()
    erg = C.ocr_art(mime, daten)
    r.check(f"{datei}: {art}", erg.get("art") == art and (scan is None or erg.get("scan_seiten") == scan), str(erg))

# The values behind the decision, per library — the OCR layer must be seen as text, but as invisible text.
werte = {}
for name, modul, fn in (("pikepdf", pikepdf, getattr(C, "_seiten_pikepdf")), ("pypdf", pypdf, getattr(C, "_seiten_pypdf"))):
    if modul is None:
        continue
    werte[name] = {d: fn(modul, (MUSTER / d).read_bytes()) for d in ERWARTET if d.endswith(".pdf")}
    w = werte[name]
    r.check(f"{name}: scan page fully covered, no text", w["scan.pdf"][0][0] == 1.0 and w["scan.pdf"][0][1:] == (0, 0),
            str(w["scan.pdf"]))
    r.check(f"{name}: OCR layer is invisible text over a full-page image",
            w["scan-ocr.pdf"][0][0] == 1.0 and w["scan-ocr.pdf"][0][1] == 0 and w["scan-ocr.pdf"][0][2] > 100,
            str(w["scan-ocr.pdf"]))
    r.check(f"{name}: digital page has visible text and no image",
            w["digital.pdf"][0][0] == 0.0 and w["digital.pdf"][0][1] >= C.SCAN_TEXT_HOECHSTENS, str(w["digital.pdf"]))
    r.check(f"{name}: letterhead page has the image AND the visible text",
            w["briefpapier.pdf"][0][0] == 1.0 and w["briefpapier.pdf"][0][1] >= C.SCAN_TEXT_HOECHSTENS,
            str(w["briefpapier.pdf"]))
if len(werte) == 2:
    r.check("pikepdf and pypdf measure the same", werte["pikepdf"] == werte["pypdf"],
            f"{werte['pikepdf']} != {werte['pypdf']}")

sys.exit(r.done())
