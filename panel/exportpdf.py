#!/usr/bin/env python3
"""PDF-Bau des Export-Knopfs: zusammenfügen, Seitenzahlen, Inhaltsverzeichnis, Links, Lesezeichen.

Nur Zeichnen und Zusammensetzen — was wohin kommt, entscheidet `exportlogik.py` (ohne diese
Bibliotheken getestet). pypdf (BSD-3-Clause) liest, fügt zusammen und setzt Links und Lesezeichen;
reportlab (BSD) zeichnet die Verzeichnisseiten und die Ebene mit den Seitenzahlen. Geprüft wird
dieses Modul im gebauten Panel-Abbild (`tests/abbild_export.py`), weil die stdlib-only-Suite die
Bibliotheken nicht hat.
"""
import io
import os
import zipfile

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.annotations import Link
from pypdf.generic import (ArrayObject, BooleanObject, DictionaryObject, NameObject, NumberObject,
                           RectangleObject, TextStringObject)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import exportlogik as el

GRAU = (0.42, 0.45, 0.50)
BLAU = (0.05, 0.36, 0.75)
_SCHRIFT = {}


def schrift():
    """(normal, fett, unicode): DejaVu Sans, wenn vorhanden — deckt Umlaute, ß, €, Ost- und
    Südosteuropäisches, Griechisch und Kyrillisch ab. Sonst Helvetica; die kann nur Windows-1252,
    alles andere wird dann zu „?" statt zu einem falschen Zeichen."""
    if "s" not in _SCHRIFT:
        pfad = os.environ.get("EXPORT_SCHRIFT") or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        fett = os.environ.get("EXPORT_SCHRIFT_FETT") or pfad.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
        try:
            pdfmetrics.registerFont(TTFont("PlSans", pfad))
            try:
                pdfmetrics.registerFont(TTFont("PlSans-Fett", fett))
                _SCHRIFT["s"] = ("PlSans", "PlSans-Fett", True)
            except Exception:
                _SCHRIFT["s"] = ("PlSans", "PlSans", True)
        except Exception:
            _SCHRIFT["s"] = ("Helvetica", "Helvetica-Bold", False)
    return _SCHRIFT["s"]


def _t(text):
    text = str(text or "")
    return text if schrift()[2] else text.encode("cp1252", "replace").decode("cp1252")


def _breite(text, font, groesse):
    return pdfmetrics.stringWidth(text, font, groesse)


def _kuerzen(text, font, groesse, platz):
    """Text auf `platz` Punkt kürzen, mit „…" am Ende — eine Zeile je Eintrag, damit die Zahl der
    Verzeichnisseiten vorab feststeht (exportlogik.toc_seiten)."""
    text = _t(text)
    if _breite(text, font, groesse) <= platz:
        return text
    while text and _breite(text + "…", font, groesse) > platz:
        text = text[:-1]
    return text.rstrip() + "…"


# ---------------------------------------------------------------- Inhaltsverzeichnis

def inhaltsverzeichnis(zeilen, kopf, unterzeile):
    """Die Verzeichnisseiten zeichnen → (pdf_bytes, links).

    `links` sind (seite, rechteck, ziel) mit ziel {"sprung": seite} (innerhalb des PDFs),
    {"uri": adresse} (Paperless), {"datei": name} (Nachbardatei, Remote-Go-To) oder
    {"relativ": name} (Nachbardatei als relativer URI). Die Links setzt `links_setzen()` mit pypdf,
    weil die Sprungziele erst im zusammengefügten PDF existieren.
    """
    normal, fett, _ = schrift()
    rechter_rand = el.SEITE_BREITE - el.RAND
    x0 = el.RAND + 28
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(el.SEITE_BREITE, el.SEITE_HOEHE), pageCompression=1)
    c.setTitle(kopf)
    c.setCreator("paperlaiss")
    links = []
    for s, seite in enumerate(el.toc_verteilen(zeilen)):
        y = el.SEITE_HOEHE - el.RAND
        if s == 0:
            c.setFont(fett, 18)
            c.drawString(el.RAND, y - 18, _t(kopf))
            c.setFont(normal, 9)
            c.setFillColorRGB(*GRAU)
            c.drawString(el.RAND, y - 36, _kuerzen(unterzeile, normal, 9, rechter_rand - el.RAND))
            c.setFillColorRGB(0, 0, 0)
            y -= el.KOPF_HOEHE
        for z in seite:
            g1, g2 = y - 12, y - 24                      # Grundlinien: Titel, Angaben
            if z["art"] == "ueberschrift":
                c.setFont(fett, 11)
                c.drawString(el.RAND, g1 - 2, _t(z["titel"]))
                y -= el.ZEILE_HOEHE
                continue
            fehlt = z["art"] == "fehlt"
            c.setFont(normal, 10.5)
            c.setFillColorRGB(*(GRAU if fehlt else (0, 0, 0)))
            c.drawRightString(x0 - 6, g1, _t(z.get("nr", "")))
            rechts = _t(z.get("rechts") or "")
            rb = _breite(rechts, normal, 10.5) if rechts else 0
            titel = _kuerzen(z["titel"], normal if fehlt else fett, 10.5, rechter_rand - x0 - rb - 14)
            c.setFont(normal if fehlt else fett, 10.5)
            c.drawString(x0, g1, titel)
            tb = _breite(titel, normal if fehlt else fett, 10.5)
            ziel = ({"sprung": z["sprung"]} if z.get("sprung") is not None
                    else {"datei": z["datei"]} if z.get("datei") else None)
            if ziel:
                links.append((s, (x0 - 2, g1 - 3, x0 + tb + 2, g1 + 11), ziel))
            if rechts:
                c.setFont(normal, 10.5)
                c.drawRightString(rechter_rand, g1, rechts)
                if ziel:
                    links.append((s, (rechter_rand - rb - 2, g1 - 3, rechter_rand + 2, g1 + 11), ziel))
            # Zweite Zeile: Angaben (grau), rechts der Link nach Paperless (blau).
            pl = "In Paperless öffnen" if z.get("paperless") else ""
            plb = _breite(_t(pl), normal, 8.5) if pl else 0
            meta = _kuerzen(z.get("meta", ""), normal, 8.5, rechter_rand - x0 - plb - 14)
            c.setFont(normal, 8.5)
            c.setFillColorRGB(*GRAU)
            c.drawString(x0, g2, meta)
            if z.get("datei"):
                # „Datei: <name>" als zweiter Weg zur Nachbardatei (relativer URI) — manche
                # Betrachter folgen nur Remote-Go-To, andere nur URIs.
                anteil = _kuerzen("Datei: " + z["datei"], normal, 8.5, _breite(meta, normal, 8.5))
                links.append((s, (x0 - 2, g2 - 3, x0 + _breite(anteil, normal, 8.5) + 2, g2 + 9),
                              {"relativ": z["datei"]}))
            if pl:
                c.setFillColorRGB(*BLAU)
                c.drawRightString(rechter_rand, g2, _t(pl))
                links.append((s, (rechter_rand - plb - 2, g2 - 3, rechter_rand + 2, g2 + 9), {"uri": z["paperless"]}))
            c.setFillColorRGB(0, 0, 0)
            y -= el.ZEILE_HOEHE
        c.showPage()
    c.save()
    return buf.getvalue(), links


def _remote_go_to(rect, datei):
    """Link auf eine Nachbardatei (PDF 1.7, 12.6.4.3 „Remote Go-To"): öffnet sie im PDF-Betrachter."""
    spez = DictionaryObject({NameObject("/Type"): NameObject("/Filespec"),
                             NameObject("/F"): TextStringObject(datei),
                             NameObject("/UF"): TextStringObject(datei)})
    return DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): RectangleObject(rect),
        NameObject("/Border"): ArrayObject([NumberObject(0)] * 3),
        NameObject("/A"): DictionaryObject({
            NameObject("/Type"): NameObject("/Action"),
            NameObject("/S"): NameObject("/GoToR"),
            NameObject("/F"): spez,
            NameObject("/D"): ArrayObject([NumberObject(0), NameObject("/Fit")]),
            NameObject("/NewWindow"): BooleanObject(True),
        }),
    })


def links_setzen(writer, links, versatz=0):
    for seite, rect, ziel in links:
        if "sprung" in ziel:
            anm = Link(rect=rect, target_page_index=ziel["sprung"])
        elif "uri" in ziel:
            anm = Link(rect=rect, url=ziel["uri"])
        elif "relativ" in ziel:
            anm = Link(rect=rect, url=el.relativer_link(ziel["relativ"]))
        else:
            anm = _remote_go_to(rect, ziel["datei"])
        writer.add_annotation(page_number=versatz + seite, annotation=anm)


# ---------------------------------------------------------------- Seitenzahlen

def seitenzahlen(writer):
    """„Seite i von n" unten mittig auf jede Seite.

    Gedrehte Seiten werden vorher ausgerichtet (die Drehung wandert in den Inhalt), sonst stünde die
    Zahl auf einem Querformat-Scan seitlich. Maßgeblich ist die sichtbare Fläche (CropBox), auch
    wenn sie nicht bei 0/0 beginnt.
    """
    normal, _, _ = schrift()
    n = len(writer.pages)
    boxen = []
    for p in writer.pages:
        if p.rotation % 360:
            p.transfer_rotation_to_content()
        box = p.cropbox
        boxen.append((float(box.left), float(box.bottom), float(box.width), float(box.height)))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pageCompression=1)
    for i, (_, _, w, h) in enumerate(boxen):
        c.setPageSize((w, h))
        c.setFont(normal, 8)
        c.setFillColorRGB(*GRAU)
        c.drawCentredString(w / 2, 14, f"Seite {i + 1} von {n}")
        c.showPage()
    c.save()
    stempel = PdfReader(io.BytesIO(buf.getvalue()))
    for i, p in enumerate(writer.pages):
        links_unten = boxen[i][:2]
        p.merge_transformed_page(stempel.pages[i], Transformation().translate(*links_unten))


# ---------------------------------------------------------------- Quelle prüfen

def pdf_pruefen(pfad):
    """Seitenzahl und ob die Lesezeichen der Quelle lesbar sind: (seiten, outline_ok).

    Ein PDF, das pypdf nicht lesen kann, wird übersprungen (ValueError mit Grund) statt den ganzen
    Export zu kippen. Ein nur mit Besitzerpasswort geschütztes PDF (Drucksperre o. ä.) öffnet sich
    mit leerem Passwort und wird entschlüsselt abgelegt; eines mit Öffnungspasswort nicht.
    """
    try:
        r = PdfReader(pfad)
        if r.is_encrypted:
            if not r.decrypt(""):
                raise ValueError("verschlüsselt (Passwort nötig)")
            w = PdfWriter(clone_from=r)
            with open(pfad + ".neu", "wb") as f:
                w.write(f)
            os.replace(pfad + ".neu", pfad)
            r = PdfReader(pfad)
        seiten = len(r.pages)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"PDF nicht lesbar ({e.__class__.__name__})") from e
    if not seiten:
        raise ValueError("PDF ohne Seiten")
    try:
        _ = r.outline
        outline_ok = True
    except Exception:
        outline_ok = False
    return seiten, outline_ok


# ---------------------------------------------------------------- Die beiden Exportarten

def ein_pdf(enthalten, fehlen, basis, ziel, *, inhalt, mit_seitenzahlen, kopf, unterzeile):
    """Alle Dokumente in ein PDF: optional Verzeichnis vorn (Sprünge + Paperless-Links), immer
    Lesezeichen je Dokument (die eigenen Lesezeichen der Quelle darunter), optional Seitenzahlen."""
    writer = PdfWriter()
    zeilen_anzahl = len(enthalten) + ((1 + len(fehlen)) if fehlen else 0)
    vorne = el.toc_seiten(zeilen_anzahl) if inhalt else 0
    starts = el.startseiten(vorne, [e["seitenzahl"] for e in enthalten])
    links = []
    if inhalt:
        zeilen = el.toc_zeilen(enthalten, fehlen, basis, sprungziele=starts)
        toc, links = inhaltsverzeichnis(zeilen, kopf, unterzeile)
        writer.append(PdfReader(io.BytesIO(toc)), import_outline=False)
        if len(writer.pages) != vorne:
            raise RuntimeError(f"Verzeichnis hat {len(writer.pages)} statt {vorne} Seiten")
        writer.add_outline_item("Inhaltsverzeichnis", 0)
    for e, start in zip(enthalten, starts):
        writer.append(e["pfad"], outline_item=el.lesezeichen(e), import_outline=e.get("outline_ok", False))
        if len(writer.pages) != start + e["seitenzahl"]:
            raise RuntimeError(f"Dokument {e['werte'].get('id')}: Seiten verschoben")
    if mit_seitenzahlen:
        seitenzahlen(writer)
    links_setzen(writer, links)
    writer.add_metadata({"/Title": kopf, "/Creator": "paperlaiss"})
    writer.page_mode = "/UseOutlines"
    with open(ziel, "wb") as f:
        writer.write(f)
    return len(writer.pages)


def einzeln(enthalten, fehlen, namen, basis, ordner, *, inhalt, inhalt_name, zip_name, kopf, unterzeile):
    """Jedes Dokument als eigene Datei (unverändert, wie Paperless es liefert), optional ein
    Verzeichnis-PDF mit Links auf die Nachbardateien und nach Paperless, optional alles als ZIP.
    Rückgabe: [(dateiname, pfad)] — eine ZIP-Datei oder die Einzeldateien."""
    ausgabe = os.path.join(ordner, "ausgabe")
    os.makedirs(ausgabe, exist_ok=True)
    dateien = []

    def pfad_fuer(name):
        p = os.path.abspath(os.path.join(ausgabe, name))
        if os.path.dirname(p) != os.path.abspath(ausgabe):       # zweite Linie nach sicherer_name()
            raise RuntimeError(f"Dateiname verlässt den Ausgabeordner: {name!r}")
        return p

    if inhalt:
        zeilen = el.toc_zeilen(enthalten, fehlen, basis, dateien=namen)
        toc, links = inhaltsverzeichnis(zeilen, kopf, unterzeile)
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(toc)))
        links_setzen(writer, links)
        writer.add_metadata({"/Title": kopf, "/Creator": "paperlaiss"})
        with open(pfad_fuer(inhalt_name), "wb") as f:
            writer.write(f)
        dateien.append((inhalt_name, pfad_fuer(inhalt_name)))
    for e, name in zip(enthalten, namen):
        os.replace(e["pfad"], pfad_fuer(name))
        dateien.append((name, pfad_fuer(name)))
    if not zip_name:
        return dateien
    zip_pfad = os.path.join(ordner, "export.zip")
    with zipfile.ZipFile(zip_pfad, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, p in dateien:
            z.write(p, arcname=name)
    for _, p in dateien:
        os.unlink(p)
    return [(zip_name, zip_pfad)]
