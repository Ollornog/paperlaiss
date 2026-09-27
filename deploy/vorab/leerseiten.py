#!/usr/bin/env python3
"""paperlaiss — Pre-Consume-Schritt: komplett weiße Seiten aus einem PDF entfernen.

Vor dem Import rendert Ghostscript jede Seite in Graustufen, und eine Seite fällt nur weg, wenn
darauf NICHTS ist außer Staub: kein dunkler Punkt, oder nur vereinzelte Punkte unter 1 mm (Staub,
Rauschen des Scanners). Eine Seitenzahl, eine winzige Zählnummer, ein Barcode, ein Strich bleiben —
„komplett weiß“ heißt komplett weiß (PO 2026-09-27).

Gemessen 2026-09-27 an 636 PDFs eines echten Archivs: die elf leeren Rückseiten hatten höchstens
35 dunkle Punkte, der größte 0,85 mm. Die knappsten Seiten mit Inhalt — eine 6-stellige Zählnummer
in 6-Punkt-Schrift, eine Seitenzahl „27“ — hatten Zeichen ab 1,5 mm und blieben alle stehen.

Nie angefasst: Dateien, die kein PDF sind; PDFs mit einer Seite; verschlüsselte, signierte (eine
Signatur zerbräche) und solche mit eingebetteten Dateien (E-Rechnung: das XML ist die Rechnung);
wären ALLE Seiten leer, bleibt das Dokument, wie es ist. Das Ergebnis ist deterministisch — gleiche
Eingabe, gleiche Datei —, damit Paperless eine Dublette weiter an der Prüfsumme erkennt.

Ein- und ausschalten über `leerseiten_entfernen` in classify-config.json (Standard: an). Das Skript
endet IMMER mit 0: ein Fehler hier darf keinen Import verhindern; im Zweifel bleibt das PDF, wie es
ist. Nur Standardbibliothek, dazu die Programme `gs` und `qpdf` aus dem Paperless-Abbild.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

DPI = 150                       # 1 Punkt ≈ 0,17 mm — Staub und Schrift lassen sich trennen
RAND = 0.02                     # Rand je Seite ausgelassen (Scannerkante, Schatten); 2 % ≈ 4–6 mm
DUNKEL = 160                    # Grauwert darunter zählt als Tinte (Durchscheinendes liegt heller)
STAUB_MM = 1.0                  # ein zusammenhängender Fleck ab dieser Ausdehnung ist Inhalt
MAX_PUNKTE = 400                # mehr dunkle Punkte: sicher keine leere Seite (Messung: höchstens 35)
STAPEL = 20                     # Seiten je Ghostscript-Aufruf (begrenzt den Platz im Temp-Ordner)
_TINTE = bytes(1 if i < DUNKEL else 0 for i in range(256))


def pgm_lesen(daten):
    """(breite, höhe, pixel) aus einem binären PGM (P5). Ghostscript schreibt eine Kommentarzeile."""
    werte, pos = [], 0
    while len(werte) < 4:
        while daten[pos:pos + 1].isspace():
            pos += 1
        if daten[pos:pos + 1] == b"#":
            pos = daten.index(b"\n", pos) + 1
            continue
        ende = pos
        while ende < len(daten) and not daten[ende:ende + 1].isspace():
            ende += 1
        werte.append(daten[pos:ende])
        pos = ende
    if werte[0] != b"P5" or int(werte[3]) > 255:
        raise ValueError("kein 8-Bit-PGM")
    w, h = int(werte[1]), int(werte[2])
    return w, h, daten[pos + 1:pos + 1 + w * h]


def seite_leer(w, h, pixel, dpi=DPI):
    """(leer?, Begründung) für eine Seite als Graustufen-Raster (eine Zeile nach der anderen, 1 Byte je Punkt)."""
    rw, rh = int(w * RAND), int(h * RAND)
    punkte = []
    for y in range(rh, h - rh):
        zeile = pixel[y * w + rw:y * w + w - rw].translate(_TINTE)
        x = zeile.find(1)
        while x != -1:
            punkte.append((y, x))
            if len(punkte) > MAX_PUNKTE:
                return False, f"mehr als {MAX_PUNKTE} dunkle Punkte"
            x = zeile.find(1, x + 1)
    if not punkte:
        return True, "weiß"
    # Zusammenhängende Flecken (8er-Nachbarschaft) — bei höchstens MAX_PUNKTE Punkten billig.
    offen, flecken = set(punkte), []
    while offen:
        stapel = [offen.pop()]
        ys, xs = [], []
        while stapel:
            y, x = stapel.pop()
            ys.append(y); xs.append(x)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    n = (y + dy, x + dx)
                    if n in offen:
                        offen.remove(n); stapel.append(n)
        flecken.append(max(max(ys) - min(ys), max(xs) - min(xs)) + 1)
    groesster = max(flecken) * 25.4 / dpi
    if groesster >= STAUB_MM:
        return False, f"Zeichen oder Strich ({groesster:.1f} mm)"
    return True, f"nur Staub ({len(flecken)} Punkte unter {STAUB_MM:g} mm)"


def einstellung(ordner):
    pfad = os.environ.get("CLASSIFY_CONFIG") or os.path.join(ordner, "classify-config.json")
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f).get("leerseiten_entfernen", True) is not False
    except (OSError, ValueError):
        return True


def _qpdf(*args):
    return subprocess.run(["qpdf", *args], capture_output=True, text=True, timeout=120)


def ausschluss(pfad):
    """Grund, das PDF nicht anzufassen — oder None."""
    if _qpdf("--is-encrypted", pfad).returncode == 0:
        return "verschlüsselt"
    with open(pfad, "rb") as f:
        roh = f.read()
    if re.search(rb"/ByteRange\s*\[|/Type\s*/Sig\b|/FT\s*/Sig\b", roh):
        return "signiert"
    anh = _qpdf("--list-attachments", pfad)
    if anh.returncode == 0 and anh.stdout.strip() and "no embedded files" not in anh.stdout.lower():
        return "mit eingebetteten Dateien"
    return None


def leere_seiten(pfad, seiten):
    """Nummern (ab 1) der leeren Seiten und je Seite die Begründung."""
    leer, gruende = [], {}
    with tempfile.TemporaryDirectory(prefix="paperlaiss-leer-") as tmp:
        for von in range(1, seiten + 1, STAPEL):
            bis = min(seiten, von + STAPEL - 1)
            muster = os.path.join(tmp, "s%05d.pgm")
            subprocess.run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pgmraw", f"-r{DPI}",
                            f"-dFirstPage={von}", f"-dLastPage={bis}", "-o", muster, pfad],
                           check=True, capture_output=True, timeout=300)
            for i in range(bis - von + 1):
                datei = muster % (i + 1)
                with open(datei, "rb") as f:
                    ist, grund = seite_leer(*pgm_lesen(f.read()))
                os.remove(datei)
                gruende[von + i] = grund
                if ist:
                    leer.append(von + i)
    return leer, gruende


def bereinigen(pfad):
    """Leere Seiten aus dem PDF entfernen (in place). Liefert die Meldung für das Paperless-Log."""
    grund = ausschluss(pfad)
    if grund:
        return f"unverändert ({grund})"
    seiten = int(_qpdf("--show-npages", pfad).stdout.strip() or 0)
    if seiten < 2:
        return "unverändert (eine Seite)"
    leer, gruende = leere_seiten(pfad, seiten)
    if not leer:
        return f"keine leere Seite ({seiten} Seiten)"
    if len(leer) == seiten:
        return f"unverändert (alle {seiten} Seiten leer)"
    bleiben = ",".join(str(s) for s in range(1, seiten + 1) if s not in leer)
    tmp = pfad + ".paperlaiss"
    r = _qpdf("--deterministic-id", pfad, "--pages", ".", bleiben, "--", tmp)
    if r.returncode not in (0, 3) or not os.path.isfile(tmp):      # 3 = mit Warnungen geschrieben
        if os.path.exists(tmp):
            os.remove(tmp)
        return f"unverändert (qpdf: {r.stderr.strip()[:200]})"
    os.replace(tmp, pfad)
    return (f"{len(leer)} von {seiten} Seiten entfernt: "
            + ", ".join(f"{s} ({gruende[s]})" for s in leer))


def ist_pdf(pfad):
    try:
        with open(pfad, "rb") as f:
            return f.read(1024).lstrip().startswith(b"%PDF-")
    except OSError:
        return False


def main():
    pfad = os.environ.get("DOCUMENT_WORKING_PATH") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not pfad or not os.path.isfile(pfad) or not ist_pdf(pfad):
        return 0
    if not einstellung(os.path.dirname(os.path.abspath(__file__))):
        return 0
    try:
        print("leerseiten: " + bereinigen(pfad), flush=True)       # stdout: Paperless loggt es als INFO
    except Exception as e:      # nie den Import aufhalten
        if os.path.exists(pfad + ".paperlaiss"):
            os.remove(pfad + ".paperlaiss")
        print(f"leerseiten: Fehler, PDF bleibt unverändert: {e!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
