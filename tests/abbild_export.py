#!/usr/bin/env python3
"""Prüfung des PDF-Baus (panel/exportpdf.py) — läuft IM gebauten Panel-Abbild.

Die stdlib-only-Suite (`tests/run_all.py`) hat weder pypdf noch reportlab noch die Schrift; dieser
Teil wird deshalb dort geprüft, wo er auch läuft: im Abbild, das der CI-Job `image` baut.

    docker build -t paperlaiss-panel:ci ./panel
    docker run --rm -v "$PWD/tests:/tests:ro" paperlaiss-panel:ci python /tests/abbild_export.py

Geprüft wird am Ergebnis, nicht am Aufruf: Seiten gezählt, Sprungziele aufgelöst, Lesezeichen
gelesen, Seitenzahlen als Text herausgelesen (auch auf gedrehten und beschnittenen Seiten), ZIP-
Inhalt und Link-Ziele gegen die Dateinamen verglichen. Fehlt eine Bibliothek, ist das ROT.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
for kandidat in (HIER.parent / "panel", Path.cwd(), Path("/app")):
    if (kandidat / "exportpdf.py").is_file():
        sys.path.insert(0, str(kandidat))
        break
from _kit.report import Report  # noqa: E402

r = Report("Abbild — PDF-Bau des Export-Knopfs (panel/exportpdf.py)")
try:
    import exportlogik as el
    import exportpdf as ep
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
except ImportError as e:                       # ohne Bibliotheken ist dieser Test wertlos → rot
    r.check("pypdf, reportlab und exportpdf importierbar", False, repr(e))
    sys.exit(r.done())

tmp = Path(tempfile.mkdtemp(prefix="abbild-export-"))
try:
    def quelle(name, seiten, groesse=(595, 842), drehen=0, crop=None, lesezeichen=False, passwort=None, besitzer=None):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=groesse)
        for i in range(seiten):
            c.drawString(80, 120, f"Inhalt {name} Seite {i + 1}")
            if lesezeichen:
                c.bookmarkPage(f"k{i}")
                c.addOutlineEntry(f"Kapitel {i + 1}", f"k{i}", 0)
            c.showPage()
        c.save()
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
        for p in w.pages:
            if drehen:
                p.rotate(drehen)
            if crop:
                p.cropbox.lower_left, p.cropbox.upper_right = crop[:2], crop[2:]
        if passwort is not None or besitzer is not None:
            w.encrypt(user_password=passwort or "", owner_password=besitzer or "besitzer", algorithm="AES-128")
        pfad = tmp / f"{name}.pdf"
        with open(pfad, "wb") as f:
            w.write(f)
        return str(pfad)

    def eintrag(i, pfad, titel, **w):
        d = el.dokument_variablen({"id": i, "title": titel, "created": f"2026-01-{i:02d}", "correspondent": 1},
                                  {"korrespondenten": {1: "Muster GmbH"}})
        d["werte"].update(w)
        d["seitenzahl"], d["outline_ok"] = ep.pdf_pruefen(pfad)
        d["pfad"] = pfad
        return d

    r.check("Schrift: DejaVu Sans im Abbild (Unicode statt Windows-1252)", ep.schrift()[2] is True, str(ep.schrift()))

    # ---- pdf_pruefen(): lesbar, Seiten, Schutz
    a = quelle("A", 2, lesezeichen=True)
    r.check("Quelle: Seiten und Lesezeichen erkannt", ep.pdf_pruefen(a) == (2, True))
    gesperrt = quelle("Gesperrt", 1, besitzer="nurbesitzer")
    try:
        r.check("Quelle: nur Besitzerpasswort (Drucksperre) → entschlüsselt übernommen",
                ep.pdf_pruefen(gesperrt)[0] == 1 and not PdfReader(gesperrt).is_encrypted)
    except ValueError as e:
        r.check("Quelle: nur Besitzerpasswort (Drucksperre) → entschlüsselt übernommen", False, str(e))
    zu = quelle("Zu", 1, passwort="geheim")
    try:
        ep.pdf_pruefen(zu)
        r.check("Quelle: Öffnungspasswort → übersprungen mit Grund", False, "keine Ausnahme")
    except ValueError as e:
        r.check("Quelle: Öffnungspasswort → übersprungen mit Grund", "Passwort" in str(e), str(e))
    kaputt = tmp / "kaputt.pdf"
    kaputt.write_bytes(b"%PDF-1.4\nkein echtes PDF")
    try:
        ep.pdf_pruefen(str(kaputt))
        r.check("Quelle: kaputtes PDF → übersprungen statt Absturz", False, "keine Ausnahme")
    except ValueError as e:
        r.check("Quelle: kaputtes PDF → übersprungen statt Absturz", "nicht lesbar" in str(e) or "ohne Seiten" in str(e), str(e))

    # ---- ein PDF: Verzeichnis, Sprünge, Paperless-Links, Lesezeichen, Seitenzahlen
    b = quelle("B", 1, drehen=90)
    c_ = quelle("C", 3, groesse=(612, 792), crop=(50, 60, 560, 700))
    enthalten = [eintrag(1, a, "Rechnung Łódź – Ångström € ő"), eintrag(2, b, "Quer gedreht"), eintrag(3, c_, "Beschnitten " * 12)]
    fehlen = [dict(el.dokument_variablen({"id": 9, "title": "Nur Text"}, {}), grund="kein PDF")]
    ziel = tmp / "ein.pdf"
    ep.ein_pdf(enthalten, fehlen, "https://dms.example.com", str(ziel), inhalt=True, mit_seitenzahlen=True,
               kopf="Inhaltsverzeichnis", unterzeile="3 Dokumente")
    rd = PdfReader(str(ziel))
    n = len(rd.pages)
    r.check("Ein PDF: 1 Verzeichnisseite + 2 + 1 + 3 Seiten", n == 7, str(n))
    seite_nr = {p.indirect_reference.idnum: i for i, p in enumerate(rd.pages)}

    def ziele(seite):
        out = []
        for a_ in rd.pages[seite].get("/Annots") or []:
            a_ = a_.get_object()
            if "/Dest" in a_:
                out.append(("sprung", seite_nr[a_["/Dest"][0].idnum]))
            elif a_.get("/A", {}).get("/S") == "/URI":
                out.append(("uri", str(a_["/A"]["/URI"])))
            elif a_.get("/A", {}).get("/S") == "/GoToR":
                out.append(("datei", str(a_["/A"]["/F"]["/UF"])))
        return out
    z = ziele(0)
    r.check("Ein PDF: Titel und „Seite n“ springen zur ersten Seite jedes Dokuments",
            [x[1] for x in z if x[0] == "sprung"] == [1, 1, 3, 3, 4, 4], str(z))
    r.check("Ein PDF: je Dokument (auch übersprungene) ein Link nach Paperless",
            [x[1] for x in z if x[0] == "uri"] == [f"https://dms.example.com/documents/{i}/details" for i in (1, 2, 3, 9)])
    text0 = rd.pages[0].extract_text()
    r.check("Ein PDF: Verzeichnis zeigt Unicode-Titel, „Seite 2“ und „Nicht enthalten“",
            "Łódź – Ångström € ő" in text0 and "Seite 2" in text0 and "Nicht enthalten (1)" in text0, text0[:300])
    r.check("Ein PDF: langer Titel gekürzt mit „…“", "Beschnitten Beschnitten" in text0 and "…" in text0)

    def lesezeichen(liste, tiefe=0):
        out = []
        for x in liste:
            if isinstance(x, list):
                out += lesezeichen(x, tiefe + 1)
            else:
                out.append((tiefe, x.title, rd.get_destination_page_number(x)))
        return out
    lz = lesezeichen(rd.outline)
    r.check("Ein PDF: Lesezeichen — Verzeichnis, je Dokument eins, darunter die der Quelle",
            lz == [(0, "Inhaltsverzeichnis", 0), (0, "Rechnung Łódź – Ångström € ő (2026-01-01)", 1),
                   (1, "Kapitel 1", 1), (1, "Kapitel 2", 2), (0, "Quer gedreht (2026-01-02)", 3),
                   (0, ("Beschnitten " * 12).strip() + " (2026-01-03)", 4)], str(lz))
    r.check("Ein PDF: öffnet mit Lesezeichenleiste", rd.trailer["/Root"].get("/PageMode") == "/UseOutlines")
    texte = [p.extract_text() for p in rd.pages]
    r.check("Ein PDF: „Seite i von 7“ auf jeder Seite", all(f"Seite {i + 1} von 7" in t for i, t in enumerate(texte)),
            str([t[-20:] for t in texte]))
    r.check("Ein PDF: Inhalt der Quellen bleibt", "Inhalt A Seite 2" in texte[2] and "Inhalt C Seite 3" in texte[6])

    def zahl_position(seite):
        pos = []
        rd.pages[seite].extract_text(visitor_text=lambda t, cm, tm, fd, fs: pos.append((tm[4], tm[5], cm)) if "Seite" in t else None)
        return pos
    box = rd.pages[4].cropbox
    x, y, cm = zahl_position(4)[-1]
    gx, gy = x * cm[0] + y * cm[2] + cm[4], x * cm[1] + y * cm[3] + cm[5]
    r.check("Ein PDF: Seitenzahl liegt im sichtbaren Bereich einer beschnittenen Seite",
            box.left <= gx <= box.right and box.bottom <= gy <= box.bottom + 40, f"{gx:.0f},{gy:.0f} in {box}")
    r.check("Ein PDF: gedrehte Seite ausgerichtet (Querformat, Drehung 0)",
            rd.pages[3].rotation == 0 and rd.pages[3].mediabox.width > rd.pages[3].mediabox.height)

    ohne = tmp / "ohne.pdf"
    ep.ein_pdf(enthalten[:1], [], "", str(ohne), inhalt=False, mit_seitenzahlen=False, kopf="x", unterzeile="y")
    ro = PdfReader(str(ohne))
    r.check("Ein PDF ohne Verzeichnis/Seitenzahlen: nur die Quelle, Lesezeichen trotzdem",
            len(ro.pages) == 2 and "Seite 1 von" not in ro.pages[0].extract_text() and ro.outline[0].title.startswith("Rechnung"))

    # Viele Dokumente: das Verzeichnis läuft über mehrere Seiten, jeder Sprung stimmt trotzdem.
    viele = [eintrag(i, quelle(f"V{i}", 1 + i % 3), f"Dokument Nummer {i}") for i in range(1, 61)]
    ziel_v = tmp / "viele.pdf"
    ep.ein_pdf(viele, [], "https://dms.example.com", str(ziel_v), inhalt=True, mit_seitenzahlen=True, kopf="Inhaltsverzeichnis", unterzeile="60")
    rd = PdfReader(str(ziel_v))
    seite_nr = {p.indirect_reference.idnum: i for i, p in enumerate(rd.pages)}
    vorne = el.toc_seiten(60)
    erwartet = el.startseiten(vorne, [e["seitenzahl"] for e in viele])
    gefunden = [x[1] for s in range(vorne) for x in ziele(s) if x[0] == "sprung"][::2]
    r.check(f"Ein PDF, 60 Dokumente: {vorne} Verzeichnisseiten, alle 60 Sprünge treffen die erste Seite",
            vorne >= 3 and gefunden == erwartet, f"{gefunden[:5]} … vs {erwartet[:5]} …")
    r.check("Ein PDF, 60 Dokumente: jede Zielseite zeigt das richtige Dokument",
            all(f"Inhalt V{i + 1} Seite 1" in rd.pages[s].extract_text() for i, s in enumerate(erwartet)))

    # ---- einzeln: Dateien unverändert, Verzeichnis-PDF mit Links, ZIP
    ordner = tmp / "einzeln"
    ordner.mkdir()
    quellen = [eintrag(i, quelle(f"E{i}", i), t) for i, t in ((1, "Rechnung März"), (2, "Rechnung März"), (3, "Vertrag"))]
    kopien = {i: Path(e["pfad"]).read_bytes() for i, e in enumerate(quellen)}
    for e in quellen:                                      # wie im Panel: Quellen liegen als quelle-<id>.pdf
        neu = ordner / f"quelle-{e['werte']['id']}.pdf"
        shutil.copy(e["pfad"], neu)
        e["pfad"] = str(neu)
    inhalt_name = el.inhalt_dateiname(True, 3)
    namen = el.dateinamen(quellen, "{titel}", True, inhalt_name)
    erg = ep.einzeln(quellen, fehlen, namen, "https://dms.example.com", str(ordner), inhalt=True, inhalt_name=inhalt_name,
                     zip_name="Export.zip", kopf="Inhaltsverzeichnis", unterzeile="3 Dateien")
    r.check("Einzeln + ZIP: genau eine Datei, das ZIP", [x[0] for x in erg] == ["Export.zip"] and zipfile.is_zipfile(erg[0][1]))
    with zipfile.ZipFile(erg[0][1]) as zf:
        mitglieder = zf.namelist()
        r.check("Einzeln + ZIP: Verzeichnis vorn, nummerierte Namen mit Umlaut",
                mitglieder == ["000_Inhaltsverzeichnis.pdf", "001_Rechnung März.pdf", "002_Rechnung März.pdf", "003_Vertrag.pdf"],
                str(mitglieder))
        r.check("Einzeln + ZIP: Dokumente byte-gleich mit Paperless (unverändert)",
                all(zf.read(namen[i]) == kopien[i] for i in range(3)))
        r.check("Einzeln + ZIP: Namen als UTF-8 markiert (Umlaute überall lesbar)",
                all(info.flag_bits & 0x800 for info in zf.infolist() if not info.filename.isascii()))
        toc = PdfReader(io.BytesIO(zf.read("000_Inhaltsverzeichnis.pdf")))
    seite_nr = {}
    rd = toc
    z = ziele(0)
    r.check("Einzeln: Titel und Dateiname verlinken die Nachbardatei (Remote-Go-To und relativer URI)",
            [x[1] for x in z if x[0] == "datei"] == namen
            and [unquote(x[1][2:]) for x in z if x[0] == "uri" and x[1].startswith("./")] == namen, str(z))
    titel_links = [x for x in z if x[0] != "uri" or not x[1].startswith("https://")][0::2]
    r.check("Einzeln: der Titel (erster Link je Zeile) ist der relative URI — dem folgt Chrome, Remote-Go-To nicht",
            all(x[0] == "uri" and x[1].startswith("./") for x in titel_links), str(titel_links))
    r.check("Einzeln: relative Links zeigen in denselben Ordner, nie hinaus",
            all(x[1].startswith("./") and "/" not in x[1][2:] for x in z if x[0] == "uri" and not x[1].startswith("http")))
    r.check("Einzeln: je Dokument ein Link nach Paperless (auch das übersprungene)",
            [x[1] for x in z if x[0] == "uri" and x[1].startswith("https://")] ==
            [f"https://dms.example.com/documents/{i}/details" for i in (1, 2, 3, 9)])
    r.check("Einzeln: Ausgabeordner aufgeräumt (nur das ZIP bleibt)",
            sorted(os.listdir(ordner / "ausgabe")) == [] and not list(ordner.glob("quelle-*.pdf")))

    ordner2 = tmp / "ohne-zip"
    ordner2.mkdir()
    q2 = [eintrag(7, quelle("F7", 1), "Einzeln")]
    shutil.copy(q2[0]["pfad"], ordner2 / "quelle-7.pdf")
    q2[0]["pfad"] = str(ordner2 / "quelle-7.pdf")
    erg2 = ep.einzeln(q2, [], ["Einzeln.pdf"], "", str(ordner2), inhalt=False, inhalt_name=None, zip_name=None,
                      kopf="x", unterzeile="y")
    r.check("Einzeln ohne ZIP und Verzeichnis: die Datei selbst", [x[0] for x in erg2] == ["Einzeln.pdf"]
            and Path(erg2[0][1]).is_file())
    try:
        ep.einzeln([dict(q2[0], pfad=str(ordner2 / "ausgabe" / "Einzeln.pdf"))], [], ["../boese.pdf"], "", str(ordner2),
                   inhalt=False, inhalt_name=None, zip_name=None, kopf="x", unterzeile="y")
        r.check("Einzeln: ein Name mit Pfad wird abgewiesen (zweite Linie)", False, "keine Ausnahme")
    except RuntimeError as e:
        r.check("Einzeln: ein Name mit Pfad wird abgewiesen (zweite Linie)", "verlässt" in str(e), str(e))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(r.done())
