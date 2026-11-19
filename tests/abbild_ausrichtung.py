#!/usr/bin/env python3
"""Upside-down pages in the Paperless image: render (Ghostscript), read twice (Tesseract), turn (qpdf) — T-8.

Runs where the step runs — in the Paperless image with gs, qpdf, tesseract and PIL; the stdlib suite has none of them:

  docker run --rm --entrypoint python3 -v "$PWD/tests:/tests:ro" -v "$PWD/deploy:/deploy:ro" \\
      ghcr.io/paperless-ngx/paperless-ngx:<version> /tests/abbild_ausrichtung.py

The test builds its own scans: a German letter, a payslip-like table and a form are typeset by Ghostscript, rendered
to a grey raster (as a scanner would) and packed as image-only PDFs, upright or turned by 180°. Checked: upside-down
scan pages are turned, upright ones and digital pages are not, the image data stays byte for byte (only /Rotate
changes), the result is deterministic, encrypted/signed files are left alone, and the step works through vorab.py.
"""
from __future__ import annotations

import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from _kit.report import Report  # noqa: E402

VORAB = Path(os.environ.get("VORAB", "/deploy/vorab"))
spec = importlib.util.spec_from_file_location("ausrichtung", VORAB / "ausrichtung.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

r = Report("Abbild-Test — Seiten kopfüber (Ghostscript, Tesseract, qpdf)")
r.check("gs, qpdf und tesseract vorhanden (sonst ist dieser Test wertlos)",
        bool(shutil.which("gs") and shutil.which("qpdf") and shutil.which("tesseract")))
try:
    from PIL import Image
except ImportError as e:
    r.check("PIL im Paperless-Abbild (baut die Test-Scans)", False, repr(e))
    sys.exit(r.done())

BRIEF = ["Stadtwerke Musterstadt GmbH", "Postfach 12 34, 12345 Musterstadt", "", "Frau Erika Mustermann",
         "Beispielweg 7", "12345 Musterstadt", "", "Jahresabrechnung Strom 2025", "Kundennummer 4711 0815",
         "", "Sehr geehrte Frau Mustermann,", "mit diesem Schreiben erhalten Sie die Abrechnung Ihres",
         "Stromverbrauchs für den Zeitraum vom 1. Januar bis 31. Dezember 2025.",
         "Der Verbrauch betrug 2.345 Kilowattstunden. Die Abschläge in Höhe von",
         "insgesamt 780,00 Euro wurden berücksichtigt. Es ergibt sich eine",
         "Gutschrift von 42,17 Euro, die wir auf Ihr Konto überweisen werden.",
         "Ihr neuer monatlicher Abschlag beträgt ab Februar 63,00 Euro.",
         "Bei Fragen erreichen Sie uns montags bis freitags von 8 bis 18 Uhr.", "",
         "Mit freundlichen Grüßen", "Ihre Stadtwerke Musterstadt"]
TABELLE = ["Entgeltabrechnung für März 2025", "Personalnummer 00123   Steuerklasse 1   Konfession --",
           "Lohnart        Bezeichnung                 Menge        Betrag",
           "1000           Gehalt                       1,00      3.250,00",
           "2010           Vermögenswirksame Leistung   1,00         40,00",
           "3100           Fahrtkostenzuschuss          1,00         55,00",
           "Gesamtbrutto                                          3.345,00",
           "Lohnsteuer                                              412,58",
           "Solidaritätszuschlag                                      0,00",
           "Krankenversicherung                                    271,95",
           "Pflegeversicherung                                      57,72",
           "Rentenversicherung                                     311,09",
           "Arbeitslosenversicherung                                43,49",
           "Nettobezug                                            2.248,17",
           "Auszahlungsbetrag                                     2.248,17"]
WENIG = ["Seite 2", "", "Anlage"]


def ps_text(zeilen, schrift=11):
    """A PostScript page that typesets the lines (Ghostscript renders it like a printed sheet)."""
    esc = lambda z: z.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    teile = [f"/Helvetica findfont {schrift} scalefont setfont"]
    y = 780
    for z in zeilen:
        teile.append(f"60 {y} moveto ({esc(z)}) show")
        y -= schrift + 7
    return ("%!PS\n<< /PageSize [595 842] >> setpagedevice\n"
            "/Helvetica findfont dup length dict begin {1 index /FID ne {def} {pop pop} ifelse} forall "
            "/Encoding ISOLatin1Encoding def currentdict end /Helvetica exch definefont pop\n"
            + "\n".join(teile) + "\nshowpage\n")


def scan(zeilen, td, kopfueber=False, schrift=11):
    """A grey raster of the typeset page, as a scanner delivers it (200 dpi, with a light grey background)."""
    ps = td / "s.ps"
    ps.write_bytes(ps_text(zeilen, schrift).encode("latin-1"))
    png = td / "s.png"
    subprocess.run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pnggray", "-r200", "-o", str(png), str(ps)],
                   check=True, capture_output=True)
    bild = Image.open(png).convert("L").point(lambda v: max(v - 12, 0) if v > 200 else v)
    return bild.rotate(180) if kopfueber else bild


def scan_pdf(pfad, bilder):
    bilder[0].save(pfad, "PDF", resolution=200, save_all=True, append_images=bilder[1:])


def bilddaten(pfad):
    """The image streams of the PDF, decoded — compared before and after."""
    roh = subprocess.run(["qpdf", "--qdf", "--object-streams=disable", str(pfad), "-"], capture_output=True).stdout
    return sorted(re.findall(rb"/Subtype /Image.*?stream\n(.*?)endstream", roh, re.S))


def drehung(pfad):
    """/Rotate of every page (pikepdf from the Paperless image)."""
    import pikepdf
    with pikepdf.open(pfad) as pdf:
        return [int(seite.obj.get("/Rotate", 0)) for seite in pdf.pages]


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    r.check("Sprachen: aus dem Abbild, ohne osd", "osd" not in A.sprachen() and "deu" in A.sprachen(),  A.sprachen())

    # ---- Stack: letter upright, letter upside down, table upside down, table upright, a page with little text
    a = td / "a.pdf"
    scan_pdf(a, [scan(BRIEF, td), scan(BRIEF, td, True), scan(TABELLE, td, True), scan(TABELLE, td),
                 scan(WENIG, td, True)])
    bild_vorher = bilddaten(a)
    t0 = time.monotonic()
    meldung = A.ausrichten(str(a))
    dauer = time.monotonic() - t0
    r.check("Kopfüber: Brief und Tabelle werden gedreht, aufrechte Seiten nicht",
            meldung.startswith("2 von 5 Seiten gedreht (180°): 2 (kopfüber") and " 3 (kopfüber" in meldung, meldung)
    r.check("Kopfüber: nur /Rotate gesetzt, an Seite 2 und 3", drehung(a) == [0, 180, 180, 0, 0], str(drehung(a)))
    r.check("Seite mit kaum Text bleibt, wie sie ist (Zweifel = nicht drehen)", drehung(a)[4] == 0)
    q = td / "q.pdf"
    scan_pdf(q, [scan(BRIEF, td).rotate(90, expand=True, fillcolor=243), scan(BRIEF, td).rotate(-90, expand=True, fillcolor=243)])
    meldung_q = A.ausrichten(str(q))
    r.check("Quer liegende Seiten (90°/270°) bleiben für Paperless' eigene Drehung", drehung(q) == [0, 0]
            and meldung_q.count("liegt quer") == 2, meldung_q)
    s3 = td / "s3.pdf"
    scan_pdf(s3, [scan(BRIEF, td, True).rotate(-3, fillcolor=243), scan(BRIEF, td).rotate(2, fillcolor=243),
                  scan(TABELLE, td, True, schrift=8)])
    meldung_s = A.ausrichten(str(s3))
    r.check("Schief kopfüber (3°) und kleine Schrift kopfüber werden gedreht, schief aufrecht nicht",
            drehung(s3) == [180, 0, 180], meldung_s)
    r.check("Bilddaten byte-gleich (verlustfrei, rückgängig zu machen)", bilddaten(a) == bild_vorher and len(bild_vorher) == 5)
    r.check("Ergebnis ist ein gültiges PDF (qpdf --check)",
            subprocess.run(["qpdf", "--check", str(a)], capture_output=True).returncode == 0)
    r.check(f"Dauer für 5 Seiten vertretbar ({dauer:.0f} s, Budget {A.BUDGET_S} s)", dauer < 120)
    r.check("Zweiter Lauf dreht nichts mehr", "keine Seite kopfüber" in A.ausrichten(str(a)), A.ausrichten(str(a)))

    # ---- deterministic: same input, byte-equal output (Paperless finds duplicates by checksum)
    b1, b2 = td / "b1.pdf", td / "b2.pdf"
    scan_pdf(b1, [scan(BRIEF, td, True)]); shutil.copy(b1, b2)
    A.ausrichten(str(b1)); A.ausrichten(str(b2))
    r.check("Deterministisch: gleiche Eingabe, byte-gleiches Ergebnis", b1.read_bytes() == b2.read_bytes()
            and drehung(b1) == [180])

    # ---- never touched
    c = td / "c.pdf"
    subprocess.run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite", "-o", str(c), str(td / "s.ps")],
                   check=True, capture_output=True)
    vorher = c.read_bytes()
    r.check("Digitale Seite (Text, kein Bild) wird nicht gelesen und nicht gedreht",
            "kein Scan" in A.ausrichten(str(c)) and c.read_bytes() == vorher)
    e0, e = td / "e0.pdf", td / "e.pdf"
    scan_pdf(e0, [scan(BRIEF, td, True)])
    subprocess.run(["qpdf", "--encrypt", "", "besitzer", "256", "--", str(e0), str(e)], check=True)
    vorher = e.read_bytes()
    r.check("Verschlüsselt → unverändert", "verschlüsselt" in A.ausrichten(str(e)) and e.read_bytes() == vorher)
    f = td / "f.pdf"
    scan_pdf(f, [scan(BRIEF, td, True)])
    f.write_bytes(f.read_bytes() + b"%% /ByteRange [0 1 2 3]\n")
    vorher = f.read_bytes()
    r.check("Signiert → unverändert", "signiert" in A.ausrichten(str(f)) and f.read_bytes() == vorher)

    # ---- as Paperless calls it: through vorab.py, working copy in DOCUMENT_WORKING_PATH; switched off by config
    h = td / "h.pdf"
    scan_pdf(h, [scan(BRIEF, td, True), scan(BRIEF, td)])
    lauf = subprocess.run([sys.executable, str(VORAB / "vorab.py")], capture_output=True, text=True, timeout=600,
                          env={**os.environ, "DOCUMENT_WORKING_PATH": str(h), "CLASSIFY_CONFIG": str(td / "keine.json")})
    r.check("Einstieg vorab.py: Seite 1 gedreht, Exit 0, Meldung im Log",
            lauf.returncode == 0 and drehung(h) == [180, 0] and "ausrichtung: 1 von 2 Seiten gedreht" in lauf.stdout,
            lauf.stdout[-300:] + lauf.stderr[-300:])
    k = td / "k.pdf"
    scan_pdf(k, [scan(BRIEF, td, True)])
    (td / "aus.json").write_text('{"kopfueber_drehen": false}')
    vorher = k.read_bytes()
    lauf = subprocess.run([sys.executable, str(VORAB / "vorab.py")], capture_output=True, text=True, timeout=600,
                          env={**os.environ, "DOCUMENT_WORKING_PATH": str(k), "CLASSIFY_CONFIG": str(td / "aus.json")})
    r.check("kopfueber_drehen: false → unverändert", lauf.returncode == 0 and k.read_bytes() == vorher, lauf.stdout[-200:])
    r.check("Keine Hilfsdatei bleibt liegen", not list(td.glob("*.paperlaiss")))

sys.exit(r.done())
