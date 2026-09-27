#!/usr/bin/env python3
"""paperlaiss — Pre-Consume-Skript für Paperless: Mails als Dokument mit Kopf und großen Bildern.

Nimmt eine Mail-Regel die GANZE Mail (Verarbeitungsumfang „.eml“), macht Paperless daraus ein PDF
über das HTML der Mail. Dieses Skript bereitet die .eml vorher auf:

  1. Kopf: Von, An, Datum und Betreff stehen oben im HTML. Mit dem Layout „nur HTML“ gibt es damit
     keine doppelte Textseite und trotzdem alle Angaben.
  2. Anhang: jedes Bild der Mail, das kein Logo, Banner oder Symbol ist, bekommt am Ende eine eigene
     Seite in voller Größe. Bilder kommen so nie ohne ihren Kontext (den Mailtext) ins Archiv.
  3. Jeder Teil ohne Content-ID bekommt eine. Paperless ersetzt `cid:<id>` durch Dateinamen — ein
     einziger Teil ohne ID macht daraus ein globales Ersetzen von `cid:`, und kein Bild erscheint.

Alles andere (PDF, Scans, Office-Dateien) bleibt unberührt. Das Skript endet IMMER mit 0: ein
Fehler hier darf keinen Import verhindern; im Zweifel bleibt die Mail, wie sie ist.

Einbinden: PAPERLESS_PRE_CONSUME_SCRIPT=<pfad>/mailbilder.py (ausführbar). Paperless übergibt die
Arbeitskopie in DOCUMENT_WORKING_PATH; die darf ein Pre-Consume-Skript verändern.
Nur Standardbibliothek: die Bildmaße liest es aus den Dateiköpfen (PNG, JPEG, GIF, WebP).
"""
import email
import email.policy
import html
import os
import re
import struct
import sys
from email.utils import make_msgid

# Was ist Deko? Gemessen 2026-09-27 an 37 Inline-Bildern eines Firmenpostfachs: 35 Logos, Banner,
# Symbole, 2 echte Bilder. Der alte Mini-Bild-Filter (klein ODER beide Seiten klein) liess 14 durch,
# darunter Werbe-Footer (700×199) und Social-Buttons (627×183). Dazu kamen Seitenverhältnis und Name.
MIN_BYTES = 6_000               # darunter: Symbol
KLEIN_LANG, KLEIN_KURZ = 600, 350   # beide Seiten so klein: Logo
MIN_KURZE_SEITE = 400           # kürzeste Seite darunter: Banner, Button, Leiste
MAX_SEITENVERHAELTNIS = 2.5     # flacher: Footer, Banner
DEKO_NAME = re.compile(r"logo|signatur|signature|footer|banner|button|icon|facebook|instagram|linkedin|"
                       r"twitter|xing|youtube|tiktok|whatsapp|pinterest", re.IGNORECASE)
BILDTYPEN = ("image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp")


def bildmasse(daten):
    """(breite, hoehe) aus dem Dateikopf oder None. PNG, GIF, WebP, JPEG (SOF-Marker)."""
    d = bytes(daten or b"")
    if d[:8] == b"\x89PNG\r\n\x1a\n" and d[12:16] == b"IHDR":
        return struct.unpack(">II", d[16:24])
    if d[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", d[6:10])
    if d[:4] == b"RIFF" and d[8:12] == b"WEBP":
        art = d[12:16]
        if art == b"VP8 " and len(d) >= 30:
            w, h = struct.unpack("<HH", d[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if art == b"VP8L" and len(d) >= 25:
            b = d[21:25]
            return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        if art == b"VP8X" and len(d) >= 30:
            return 1 + int.from_bytes(d[24:27], "little"), 1 + int.from_bytes(d[27:30], "little")
        return None
    if d[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(d):
            if d[i] != 0xFF:
                i += 1
                continue
            marker = d[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            laenge = struct.unpack(">H", d[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", d[i + 5:i + 9])
                return w, h
            i += 2 + laenge
    return None


def ist_inhalt(name, daten):
    """True, wenn ein Bild als eigene Seite gezeigt wird; (False, Grund) sonst."""
    groesse = len(daten or b"")
    if DEKO_NAME.search(name or ""):
        return False, "Name nach Logo/Symbol"
    if groesse <= MIN_BYTES:
        return False, f"klein ({groesse} B)"
    masse = bildmasse(daten)
    if not masse or not all(masse):
        return False, "Maße nicht lesbar"
    lang, kurz = max(masse), min(masse)
    if lang <= KLEIN_LANG and kurz <= KLEIN_KURZ:
        return False, f"Logo-Format {masse[0]}×{masse[1]}"
    if kurz < MIN_KURZE_SEITE:
        return False, f"schmal {masse[0]}×{masse[1]}"
    if lang / kurz > MAX_SEITENVERHAELTNIS:
        return False, f"Banner-Format {masse[0]}×{masse[1]}"
    return True, f"{masse[0]}×{masse[1]}"


# Bilder im Mailtext: höchstens seitenbreit und 9 cm hoch (Vorschau). Ohne das legt Chromium ein Foto in
# Originalgröße über mehrere Seiten (gemessen: 2540×3795 → drei Seiten). In voller Größe erscheint es auf
# seiner Anhangsseite (Klasse pl-gross). Klasse statt src-Selektor: Paperless schreibt die cid-Verweise um.
STIL = ("<style>img{max-width:100%!important;max-height:9cm!important;width:auto!important;"
        "height:auto!important}img.pl-gross{max-height:26.5cm!important}"
        # Leere Absätze am Mailende schoben sonst eine leere letzte Seite nach (gemessen an einer Signatur-Mail).
        "p:empty{display:none!important}</style>")


def _kopf_html(msg):
    zeilen = [(k, msg.get(h)) for k, h in (("Von", "From"), ("An", "To"), ("Kopie", "Cc"), ("Datum", "Date"),
                                             ("Betreff", "Subject"))]
    zellen = "".join(f'<tr><td style="padding:1px 12px 1px 0;color:#555;vertical-align:top">{k}</td>'
                     f'<td style="padding:1px 0">{html.escape(str(v))}</td></tr>' for k, v in zeilen if v)
    return (STIL + '<div data-paperlaiss="kopf" style="font:13px/1.4 sans-serif;border-bottom:1px solid #999;'
            f'margin:0 0 12px;padding:0 0 8px"><table style="border-collapse:collapse">{zellen}</table></div>')


def _anhang_html(bilder):
    if not bilder:
        return ""
    teile = ['<div data-paperlaiss="bilder" style="font:13px/1.4 sans-serif">']
    for name, cid, masse in bilder:
        teile.append('<div style="break-before:page;page-break-before:always;text-align:center">'
                     f'<p style="margin:0 0 6px;color:#555">Anhang: Bild aus der Mail — {html.escape(name)} ({masse})</p>'
                     f'<img class="pl-gross" src="cid:{html.escape(cid)}" alt="{html.escape(name)}" '
                     'style="max-width:100%;max-height:26.5cm;width:auto;height:auto"></div>')
    teile.append("</div>")
    return "".join(teile)


def _html_teil(msg):
    """Der Hauptteil text/html (kein Anhang) oder None."""
    for teil in msg.walk():
        if teil.get_content_type() == "text/html" and teil.get_content_disposition() != "attachment":
            return teil
    return None


def _text_teil(msg):
    for teil in msg.walk():
        if teil.get_content_type() == "text/plain" and teil.get_content_disposition() != "attachment":
            return teil
    return None


def aufbereiten(roh):
    """Rohe .eml-Bytes → (neue Bytes oder None wenn nichts zu tun, Protokollzeilen)."""
    msg = email.message_from_bytes(roh, policy=email.policy.default)
    log = []
    geaendert = False
    bilder = []
    for n, teil in enumerate(msg.walk()):
        if teil.is_multipart() or (teil.get_content_maintype() == "text"
                                   and teil.get_content_disposition() != "attachment"):
            continue
        if not teil.get("Content-ID"):
            teil["Content-ID"] = make_msgid(f"paperlaiss{n}", "lokal")
            geaendert = True
        if teil.get_content_type() in BILDTYPEN:
            name = teil.get_filename() or f"bild-{n}"
            daten = teil.get_payload(decode=True) or b""
            ja, grund = ist_inhalt(name, daten)
            log.append(f"{'Seite' if ja else 'weg  '} {name}: {grund}")
            if ja:
                bilder.append((name, str(teil["Content-ID"]).strip("<> "), grund))

    kopf, anhang = _kopf_html(msg), _anhang_html(bilder)
    htmlteil = _html_teil(msg)
    if htmlteil is not None:
        text = htmlteil.get_content()
        if 'data-paperlaiss="kopf"' in text:
            return None, log + ["schon aufbereitet"]
        m = re.search(r"<body[^>]*>", text, re.IGNORECASE)
        text = (text[:m.end()] + kopf + text[m.end():]) if m else kopf + text
        m = None
        for m in re.finditer(r"</body\s*>", text, re.IGNORECASE):
            pass
        text = (text[:m.start()] + anhang + text[m.start():]) if m else text + anhang
        htmlteil.set_content(text, subtype="html", charset="utf-8")
        return msg.as_bytes(policy=email.policy.SMTP), log + ["HTML: Kopf + %d Bildseite(n)" % len(bilder)]

    if not bilder:
        # Reine Textmail ohne Bilder: Paperless zeigt Kopf und Text schon auf seiner Textseite.
        return (msg.as_bytes(policy=email.policy.SMTP) if geaendert else None), log + ["Textmail ohne Bilder — unverändert"]

    texteil = _text_teil(msg)
    koerper = html.escape(texteil.get_content()) if texteil is not None else ""
    neu = ('<html><body>' + kopf + f'<pre style="white-space:pre-wrap;font:13px/1.4 sans-serif">{koerper}</pre>'
           + anhang + "</body></html>")
    if not msg.is_multipart():
        msg.make_mixed()
    msg.add_attachment(neu, subtype="html", charset="utf-8", disposition="inline")
    return msg.as_bytes(policy=email.policy.SMTP), log + ["Textmail: HTML-Teil angelegt, %d Bildseite(n)" % len(bilder)]


def main():
    pfad = os.environ.get("DOCUMENT_WORKING_PATH") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not pfad.lower().endswith(".eml") or not os.path.isfile(pfad):
        return 0
    try:
        with open(pfad, "rb") as f:
            neu, log = aufbereiten(f.read())
        if neu is not None:
            tmp = pfad + ".paperlaiss"
            with open(tmp, "wb") as f:
                f.write(neu)
            os.replace(tmp, pfad)
        print("mailbilder: " + " | ".join(log), file=sys.stderr)
    except Exception as e:      # nie den Import aufhalten
        print(f"mailbilder: Fehler, Mail bleibt unverändert: {e!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
