#!/usr/bin/env python3
"""Leerseiten im Paperless-Abbild: Rendern (Ghostscript) und Entfernen (qpdf) an echten PDFs.

Läuft dort, wo das Skript auch läuft — im Paperless-Abbild, das gs und qpdf mitbringt; die
stdlib-Suite hat beides nicht. Aufruf (CI-Job „leerseiten“):

  docker run --rm --entrypoint python3 -v "$PWD/tests:/tests:ro" -v "$PWD/deploy:/deploy:ro" \\
      ghcr.io/paperless-ngx/paperless-ngx:<version> /tests/abbild_leerseiten.py

Die Test-PDFs baut der Test selbst (Seiten mit Text, leer, Staub, nur Seitenzahl).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from _kit.report import Report  # noqa: E402

VORAB = Path(os.environ.get("VORAB", "/deploy/vorab"))
spec = importlib.util.spec_from_file_location("leerseiten", VORAB / "leerseiten.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

r = Report("Abbild-Test — Leerseiten mit Ghostscript und qpdf")
r.check("gs und qpdf vorhanden (sonst ist dieser Test wertlos)", bool(shutil.which("gs") and shutil.which("qpdf")))

INHALT = "BT /F1 14 Tf 72 700 Td (Inhalt Seite {n}) Tj ET"
LEER = ""
STAUB = " ".join(f"0 g {100 + 37 * i} {150 + 53 * i} 0.8 0.8 re f" for i in range(8))    # Punkte 0,3 mm
NUMMER = "BT /F1 8 Tf 290 40 Td (3) Tj ET"                                               # nur eine Seitenzahl


def pdf_bauen(pfad, seiten, extra=b""):
    """Kleines gültiges PDF: eine Seite je Inhaltsstrom, Helvetica als Schrift."""
    objekte = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kinder = []
    for i, strom in enumerate(seiten, 1):
        s = strom.replace("{n}", str(i)).encode()
        objekte.append(b"<< /Length %d >>\nstream\n" % len(s) + s + b"\nendstream")
        inhalt = len(objekte)
        objekte.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                       b"/Resources << /Font << /F1 3 0 R >> >> >>" % inhalt)
        kinder.append(len(objekte))
    objekte[1] = (b"<< /Type /Pages /Count %d /Kids [" % len(kinder)
                  + b" ".join(b"%d 0 R" % k for k in kinder) + b"] >>")
    aus = bytearray(b"%PDF-1.7\n")
    lagen = []
    for nr, o in enumerate(objekte, 1):
        lagen.append(len(aus))
        aus += b"%d 0 obj\n" % nr + o + b"\nendobj\n"
    xref = len(aus)
    aus += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1)
    aus += b"".join(b"%010d 00000 n \n" % l for l in lagen)
    aus += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objekte) + 1, xref) + extra
    Path(pfad).write_bytes(bytes(aus))


def texte(pfad):
    """Text je Seite — über Ghostscript (txtwrite), pdftotext braucht es nicht."""
    t = subprocess.run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=txtwrite", "-o", "-", str(pfad)],
                       capture_output=True, text=True).stdout
    return t


def seiten(pfad):
    return int(subprocess.run(["qpdf", "--show-npages", str(pfad)], capture_output=True, text=True).stdout.strip() or 0)


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    # ---- Das Normale: Inhalt, leer, Staub, Inhalt, nur Seitenzahl
    a = td / "a.pdf"
    pdf_bauen(a, [INHALT, LEER, STAUB, INHALT, NUMMER])
    meldung = L.bereinigen(str(a))
    r.check("Entfernt: die leere Seite und die Seite mit Staub (2 von 5)", seiten(a) == 3 and "2 von 5" in meldung, meldung)
    t = texte(a)
    r.check("Bleibt: beide Inhaltsseiten und die Seite, auf der nur „3“ steht, in alter Reihenfolge",
            t.find("Inhalt Seite 1") < t.find("Inhalt Seite 4") and "3" in t.split("Inhalt Seite 4")[-1], t[:300])
    r.check("Ergebnis ist ein gültiges PDF (qpdf --check)",
            subprocess.run(["qpdf", "--check", str(a)], capture_output=True).returncode == 0)

    # ---- Deterministisch: zweimal dieselbe Eingabe → byte-gleiche Datei (Paperless: Dubletten per Prüfsumme)
    b1, b2 = td / "b1.pdf", td / "b2.pdf"
    pdf_bauen(b1, [INHALT, LEER, INHALT]); shutil.copy(b1, b2)
    L.bereinigen(str(b1)); L.bereinigen(str(b2))
    r.check("Deterministisch: gleiche Eingabe, byte-gleiches Ergebnis", b1.read_bytes() == b2.read_bytes() and seiten(b1) == 2)
    r.check("Zweiter Lauf ändert nichts mehr", "keine leere Seite" in L.bereinigen(str(b1)))

    # ---- Nie angefasst
    c = td / "c.pdf"; pdf_bauen(c, [LEER, LEER, STAUB]); vorher = c.read_bytes()
    r.check("Alle Seiten leer → unverändert", "alle 3 Seiten leer" in L.bereinigen(str(c)) and c.read_bytes() == vorher)
    d = td / "d.pdf"; pdf_bauen(d, [LEER]); vorher = d.read_bytes()
    r.check("Eine Seite → unverändert", "eine Seite" in L.bereinigen(str(d)) and d.read_bytes() == vorher)
    e = td / "e.pdf"; pdf_bauen(e, [INHALT, LEER], extra=b"%% /ByteRange [0 1 2 3]\n"); vorher = e.read_bytes()
    r.check("Signiert (ByteRange) → unverändert", "signiert" in L.bereinigen(str(e)) and e.read_bytes() == vorher)
    f0, f = td / "f0.pdf", td / "f.pdf"; pdf_bauen(f0, [INHALT, LEER])
    subprocess.run(["qpdf", "--encrypt", "", "besitzer", "256", "--", str(f0), str(f)], check=True)
    vorher = f.read_bytes()
    r.check("Verschlüsselt → unverändert", "verschlüsselt" in L.bereinigen(str(f)) and f.read_bytes() == vorher)
    g0, g = td / "g0.pdf", td / "g.pdf"; pdf_bauen(g0, [INHALT, LEER])
    (td / "rechnung.xml").write_text("<Invoice/>")
    subprocess.run(["qpdf", str(g0), "--add-attachment", str(td / "rechnung.xml"), "--", str(g)], check=True)
    vorher = g.read_bytes()
    r.check("Mit eingebetteter Datei (E-Rechnung) → unverändert", "eingebetteten" in L.bereinigen(str(g)) and g.read_bytes() == vorher)

    # ---- Aufruf wie durch Paperless: über den Einstieg vorab.py, Arbeitskopie in DOCUMENT_WORKING_PATH
    h = td / "h.pdf"; pdf_bauen(h, [INHALT, LEER, INHALT])
    lauf = subprocess.run([sys.executable, str(VORAB / "vorab.py")], capture_output=True, text=True, timeout=300,
                          env={**os.environ, "DOCUMENT_WORKING_PATH": str(h)})
    r.check("Einstieg vorab.py: PDF verliert die leere Seite, Exit 0, Meldung im Log",
            lauf.returncode == 0 and seiten(h) == 2 and "1 von 3 Seiten entfernt" in lauf.stdout, lauf.stdout[-300:] + lauf.stderr[-300:])
    r.check("Keine Hilfsdatei bleibt liegen", not list(td.glob("*.paperlaiss")))

    # ---- Viele Seiten: Stapelweise gerendert, Nummern stimmen über Stapelgrenzen hinweg
    v = td / "v.pdf"
    pdf_bauen(v, [LEER if i in (1, 20, 21, 44) else INHALT for i in range(1, 46)])
    meldung = L.bereinigen(str(v))
    r.check("45 Seiten über 3 Stapel: genau 1, 20, 21 und 44 fallen", seiten(v) == 41
            and meldung.startswith("4 von 45 Seiten entfernt: 1 (weiß), 20 (weiß), 21 (weiß), 44 (weiß)"), meldung)

sys.exit(r.done())
