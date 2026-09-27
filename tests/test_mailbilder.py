#!/usr/bin/env python3
"""Fachtest: deploy/mail-pdf/mailbilder.py — Mail als Dokument mit Kopf und großen Bildern.

Bildmaße aus Dateiköpfen, das Deko-Urteil (mit den am echten Postfach gemessenen Fällen), die
Aufbereitung der .eml (Kopf, Bildseiten, Content-IDs, reine Textmail) und dass das Skript nie
einen Import aufhält. Stdlib-only.
"""
from __future__ import annotations

import email
import email.policy
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from _kit.report import Report  # noqa: E402

SKRIPT = ROOT / "deploy" / "mail-pdf" / "mailbilder.py"
spec = importlib.util.spec_from_file_location("mailbilder", SKRIPT)
mb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mb)

r = Report("Fachtest — deploy/mail-pdf/mailbilder.py (Mail-PDF mit Bildern)")


def png(w, h, auffuellen=0):
    """Echtes kleines PNG mit gewünschten Maßen im Kopf (Inhalt 1×1 reicht dem Kopfleser nicht —
    also korrekter IHDR), dazu Füllbytes, damit die Dateigröße realistisch ist."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\0" * 10))
            + chunk(b"IEND", b"") + b"\0" * auffuellen)


def jpeg(w, h, auffuellen=0):
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0" + b"\0" * 9 + sof + b"\0" * auffuellen + b"\xff\xd9"


# ---- Bildmaße aus dem Dateikopf
r.check("Maße: PNG", mb.bildmasse(png(2540, 3795)) == (2540, 3795))
r.check("Maße: JPEG (SOF0 hinter APP0)", mb.bildmasse(jpeg(700, 199)) == (700, 199), str(mb.bildmasse(jpeg(700, 199))))
r.check("Maße: GIF", mb.bildmasse(b"GIF89a" + struct.pack("<HH", 215, 82) + b"\0" * 20) == (215, 82))
_vp8x = b"RIFF" + b"\0\0\0\0" + b"WEBPVP8X" + b"\0" * 8 + (1439).to_bytes(3, "little") + (3119).to_bytes(3, "little")
r.check("Maße: WebP (VP8X)", mb.bildmasse(_vp8x) == (1440, 3120), str(mb.bildmasse(_vp8x)))
r.check("Maße: Unbekanntes ergibt None", mb.bildmasse(b"kein bild") is None and mb.bildmasse(b"") is None)

# ---- Deko-Urteil: die am echten Postfach gemessenen Fälle (2026-09-27, 37 Inline-Bilder)
_faelle = [
    ("IMG_0923.jpg", jpeg(2540, 3795, 2_000_000), True),              # Foto eines Schadens
    ("1000070598.png", png(1440, 3120, 300_000), True),               # Bildschirmfoto
    ("footer_kampagne.png", png(700, 199, 200_000), False),           # Werbe-Footer
    ("image005.jpg", jpeg(697, 154, 40_000), False),                  # Banner
    ("72-722799_follow-us.png", png(627, 183, 35_000), False),        # Social-Button
    ("image001.png", png(1688, 636, 95_000), False),                  # breites Banner (2,65 : 1)
    ("Logo Neu Mail Signatur.jpg", jpeg(684, 565, 50_000), False),    # Signaturlogo, fast quadratisch
    ("image.png", png(383, 184, 18_000), False),                      # kleines Logo
    ("pl24logo", png(306, 64, 3_000), False),                         # Symbol
]
_falsch = [(n, mb.ist_inhalt(n, d)) for n, d, soll in _faelle if mb.ist_inhalt(n, d)[0] != soll]
r.check("Deko-Urteil: die gemessenen Fälle — 2 Bilder bleiben, alle Logos/Banner/Buttons fallen", not _falsch, str(_falsch))
r.check("Deko-Urteil: nennt den Grund", "Banner" in mb.ist_inhalt("x.png", png(1688, 636, 95_000))[1])


def mail_html(teile_bilder, text_html="<html><body><p>Hagelschaden instandgesetzt.</p></body></html>"):
    m = EmailMessage()
    m["From"] = "Absender <a@example.com>"; m["To"] = "b@example.com"; m["Subject"] = "Fwd: Hagelschaden"
    m["Date"] = "Fri, 18 Sep 2026 11:38:40 +0200"
    m.set_content("Hagelschaden instandgesetzt.")
    m.add_alternative(text_html, subtype="html")
    for name, daten, cid in teile_bilder:
        html_teil = m.get_payload()[1]
        html_teil.add_related(daten, maintype="image", subtype="png" if daten[:4] == b"\x89PNG" else "jpeg",
                              cid=cid, filename=name, disposition="inline")
    return m.as_bytes(policy=email.policy.SMTP)


def html_von(roh):
    m = email.message_from_bytes(roh, policy=email.policy.default)
    return next((t.get_content() for t in m.walk() if t.get_content_type() == "text/html"
                 and t.get_content_disposition() != "attachment"), "")


# ---- Aufbereitung: HTML-Mail mit Foto und Banner
_roh = mail_html([("IMG_0923.jpg", jpeg(2540, 3795, 60_000), "<foto@x>"), ("footer.png", png(700, 199, 30_000), "<banner@x>")])
_neu, _log = mb.aufbereiten(_roh)
_h = html_von(_neu)
r.check("HTML-Mail: Kopf mit Von, Datum und Betreff steht oben im HTML",
        'data-paperlaiss="kopf"' in _h and "Fwd: Hagelschaden" in _h and "a@example.com" in _h
        and _h.index('data-paperlaiss="kopf"') < _h.index("Hagelschaden instandgesetzt"), _h[:300])
_anhang = _h[_h.index('data-paperlaiss="bilder"'):] if 'data-paperlaiss="bilder"' in _h else ""
r.check("HTML-Mail: das Foto bekommt eine eigene Seite (cid-Verweis, Seitenumbruch), der Banner nicht",
        'src="cid:foto@x"' in _anhang and "cid:banner@x" not in _anhang and "break-before:page" in _anhang, _anhang[:400])
r.check("HTML-Mail: Bilder im Mailtext werden begrenzt (Vorschau), die Anhangsseite zeigt groß",
        "max-height:9cm!important" in _h and 'class="pl-gross" src="cid:foto@x"' in _anhang
        and "img.pl-gross{max-height:26.5cm!important}" in _h)
r.check("HTML-Mail: Bildseiten stehen am Ende, nach dem Mailtext",
        _h.index('data-paperlaiss="bilder"') > _h.index("Hagelschaden instandgesetzt"))
r.check("HTML-Mail: zweiter Lauf ändert nichts (schon aufbereitet)", mb.aufbereiten(_neu)[0] is None)

# ---- Content-ID für jeden Teil (sonst ersetzt Paperless `cid:` global und kein Bild erscheint)
_m = email.message_from_bytes(_roh, policy=email.policy.default)
_m.add_attachment(b"BEGIN:VCALENDAR", maintype="text", subtype="calendar", filename="termin.ics")
_m.add_attachment(jpeg(2000, 1500, 50_000), maintype="image", subtype="jpeg", filename="scan.jpg")
_neu2, _ = mb.aufbereiten(_m.as_bytes(policy=email.policy.SMTP))
_ohne = [t.get_filename() for t in email.message_from_bytes(_neu2, policy=email.policy.default).walk()
         if not t.is_multipart() and not (t.get_content_maintype() == "text" and t.get_content_disposition() != "attachment")
         and not t.get("Content-ID")]
r.check("Content-ID: jeder Anhang-Teil hat danach eine", not _ohne, str(_ohne))
r.check("Content-ID: ein Bild-Anhang ohne ID wird trotzdem als Seite gezeigt",
        "Anhang: Bild aus der Mail — scan.jpg" in html_von(_neu2))

# ---- Reine Textmail
_t = EmailMessage(); _t["From"] = "a@example.com"; _t["Subject"] = "Foto"; _t.set_content("Siehe Foto <b>anbei</b>.")
_t.add_attachment(jpeg(3000, 4000, 80_000), maintype="image", subtype="jpeg", filename="IMG_1.jpg", disposition="inline")
_neu3, _log3 = mb.aufbereiten(_t.as_bytes(policy=email.policy.SMTP))
_h3 = html_von(_neu3)
r.check("Textmail mit Foto: HTML-Teil angelegt (sonst ignoriert Paperless das Layout) mit Text und Bildseite",
        _neu3 is not None and "Siehe Foto &lt;b&gt;anbei&lt;/b&gt;." in _h3 and "IMG_1.jpg" in _h3, str(_log3))
_t2 = EmailMessage(); _t2["From"] = "a@example.com"; _t2.set_content("Nur Text.")
r.check("Textmail ohne Bild: bleibt unverändert", mb.aufbereiten(_t2.as_bytes(policy=email.policy.SMTP))[0] is None)
_nur_logo = mail_html([("logo.png", png(300, 80, 9_000), "<l@x>")])
r.check("HTML-Mail nur mit Logo: Kopf ja, keine Bildseite",
        'data-paperlaiss="bilder"' not in html_von(mb.aufbereiten(_nur_logo)[0])
        and 'data-paperlaiss="kopf"' in html_von(mb.aufbereiten(_nur_logo)[0]))

# ---- Aufruf wie durch Paperless: nie den Import aufhalten
with tempfile.TemporaryDirectory() as _td:
    _eml = Path(_td, "mail.eml"); _eml.write_bytes(_roh)
    _pdf = Path(_td, "rechnung.pdf"); _pdf.write_bytes(b"%PDF-1.7 unveraendert")
    _kaputt = Path(_td, "kaputt.eml"); _kaputt.write_bytes(b"\xff\xfe" + b"\0" * 50)

    def lauf(pfad):
        return subprocess.run([sys.executable, str(SKRIPT)], env={**os.environ, "DOCUMENT_WORKING_PATH": str(pfad)},
                              capture_output=True, text=True, timeout=60)
    _a, _b, _c = lauf(_eml), lauf(_pdf), lauf(_kaputt)
    r.check("Aufruf: .eml wird in der Arbeitskopie aufbereitet, Exit 0",
            _a.returncode == 0 and b'data-paperlaiss="kopf"' in _eml.read_bytes().replace(b"=\r\n", b"").replace(b"=3D", b"="), _a.stderr[-200:])
    r.check("Aufruf: ein PDF bleibt Byte für Byte unverändert, Exit 0",
            _b.returncode == 0 and _pdf.read_bytes() == b"%PDF-1.7 unveraendert")
    r.check("Aufruf: eine kaputte .eml hält den Import nicht auf (Exit 0)", _c.returncode == 0, _c.stderr[-200:])
    r.check("Aufruf: keine Hilfsdatei bleibt liegen", not list(Path(_td).glob("*.paperlaiss")))
r.check("Skript ist ausführbar (Paperless ruft es direkt auf)", os.access(SKRIPT, os.X_OK))

sys.exit(r.done())
