#!/usr/bin/env python3
"""paperlaiss — pre-consume step: turn pages of a scan that lie upside down (backlog T-8).

In a stack scan part of the sheets lies the wrong way round. Paperless turns pages with Tesseract's orientation
detection (OSD) before its OCR, and that is reliable for 90°, but not for 180°: on a batch of 117 documents 25 lay
upside down and stayed so, while OSD called every tax notice "180°" at a confidence below the threshold. An upside-down
page is then archived as gibberish, and the classifier works on it.

Here every scanned page is read twice by Tesseract — as it is and turned by 180° — and compared by the number of
well-recognised words (confidence of at least WORT_KONFIDENZ, three characters or more). A page is turned when the
turned reading has clearly more of them (GEDREHT_FAKTOR, at least MIN_WOERTER); a page that reads well as it is
(GUT_GENUG) is not read a second time. Only pages that carry a scanned image are checked: the page is rendered with
images only (`-dFILTERTEXT -dFILTERVECTOR`), so a digital page and the invisible OCR layer of a scanner are left out.

What changes in the file: only the `/Rotate` entry of the turned pages (qpdf `--rotate`). The image data stays byte for
byte as it was, so the step is lossless and can be undone with Paperless' own rotate; the result is deterministic, so
Paperless still recognises a duplicate by its checksum. Never touched: files that are no PDF, encrypted or signed PDFs
(a signature would break) and PDFs with embedded files (e-invoice). The step ends ALWAYS with 0 and replaces the
working copy only at the end and atomically: an error, a missing tool or the time budget leaves the PDF as it was
(the time budget keeps the pages found so far).

On and off with `kopfueber_drehen` in classify-config.json (default: on). Languages: `PAPERLESS_OCR_LANGUAGE`
(as Paperless reads), otherwise every installed language except `osd`. Standard library only, plus `gs`, `qpdf` and
`tesseract` from the Paperless image.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

DPI = 150
DUNKEL = 160                    # grey value below counts as ink (as leerseiten.py)
MIN_TINTE = 0.003               # share of ink pixels in the image layer below which a page holds no scan
WORT_KONFIDENZ = 75             # Tesseract confidence (0–100) from which a word counts as well recognised
MIN_WOERTER = 12                # the turned reading needs at least so many good words
GEDREHT_FAKTOR = 3              # … and so many times the good words of the page as it is
GUT_GENUG = 40                  # good words as it is from which a second reading is not needed
MAX_SEITEN = 60                 # pages checked at most (a thick stack is checked from the start)
BUDGET_S = 240                  # all pages together; vorab.py ends a step after 300 s
SEITE_S = 60                    # one Tesseract call
_TINTE = bytes(1 if i < DUNKEL else 0 for i in range(256))


def _nachbar(name):
    """leerseiten.py from the same folder (PGM reader, exclusions) — one place for both steps."""
    spec = importlib.util.spec_from_file_location(f"paperlaiss_{name}",
                                                  os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


L = _nachbar("leerseiten")


def einstellung(ordner):
    pfad = os.environ.get("CLASSIFY_CONFIG") or os.path.join(ordner, "classify-config.json")
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f).get("kopfueber_drehen", True) is not False
    except (OSError, ValueError):
        return True


def sprachen(env=None, vorhanden=None):
    """Tesseract languages: PAPERLESS_OCR_LANGUAGE where installed, else every installed one but osd."""
    env = os.environ if env is None else env
    if vorhanden is None:
        r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=30)
        vorhanden = [z.strip() for z in r.stdout.splitlines()[1:] if z.strip()]
    vorhanden = [s for s in vorhanden if s != "osd"]
    gewuenscht = [s for s in (env.get("PAPERLESS_OCR_LANGUAGE") or "").split("+") if s.strip()]
    gewaehlt = [s for s in gewuenscht if s in vorhanden] or vorhanden
    return "+".join(gewaehlt)


def gute_woerter(tsv):
    """(well-recognised words, of which standing upright in the raster) from Tesseract's TSV output (level 5 = word).

    A word box higher than wide is text running up or down the page: Tesseract reads a page lying at 90° in its
    layout analysis too, and such a page is no case for 180° (Paperless' own rotation turns it reliably)."""
    n = quer = 0
    for zeile in tsv.splitlines()[1:]:
        teile = zeile.split("\t")
        if len(teile) < 12 or teile[0] != "5":
            continue
        try:
            konf, breite, hoehe = float(teile[10]), int(teile[8]), int(teile[9])
        except ValueError:
            continue
        wort = teile[11].strip()
        if konf >= WORT_KONFIDENZ and len(wort) >= 3 and sum(c.isalnum() for c in wort) >= 3:
            n += 1
            quer += hoehe > breite
    return n, quer


def gedreht_besser(normal, gedreht):
    """Turn the page? Only when the turned reading is clearly better — a doubt leaves the page as it is."""
    return gedreht >= MIN_WOERTER and gedreht >= GEDREHT_FAKTOR * max(normal, 1)


def pgm(w, h, pixel):
    return f"P5\n{w} {h}\n255\n".encode() + pixel


def hat_scan(w, h, pixel):
    return pixel.translate(_TINTE).count(1) >= MIN_TINTE * w * h


def lesen(pfad, sprache):
    r = subprocess.run(["tesseract", pfad, "stdout", "-l", sprache, "--psm", "3", "tsv"],
                       capture_output=True, text=True, timeout=SEITE_S)
    return gute_woerter(r.stdout)


def _quer(n, quer):
    return n > 0 and quer * 2 > n


def seite_pruefen(w, h, pixel, sprache, tmp, lesen_=None):
    """(turn?, reason) for one page rendered as grey raster. A 180° turn of a raster is its bytes reversed."""
    lesen_ = lesen_ or lesen
    if not hat_scan(w, h, pixel):
        return False, "kein Scan"
    datei = os.path.join(tmp, "seite.pgm")
    with open(datei, "wb") as f:
        f.write(pgm(w, h, pixel))
    normal, q_normal = lesen_(datei, sprache)
    if _quer(normal, q_normal):
        return False, f"liegt quer ({normal} Wörter, das dreht Paperless)"
    if normal >= GUT_GENUG:
        return False, f"aufrecht ({normal} Wörter)"
    with open(datei, "wb") as f:
        f.write(pgm(w, h, pixel[::-1]))
    gedreht, q_gedreht = lesen_(datei, sprache)
    if _quer(gedreht, q_gedreht):
        return False, f"liegt quer ({gedreht} Wörter gedreht, das dreht Paperless)"
    if gedreht_besser(normal, gedreht):
        return True, f"kopfüber ({normal} Wörter, gedreht {gedreht})"
    return False, f"bleibt ({normal} Wörter, gedreht {gedreht})"


def kopfueber_seiten(pfad, seiten, sprache, lesen_=None, uhr=time.monotonic):
    """Page numbers (from 1) that lie upside down, and a reason per checked page."""
    kopf, gruende, start = [], {}, uhr()
    with tempfile.TemporaryDirectory(prefix="paperlaiss-lage-") as tmp:
        for s in range(1, min(seiten, MAX_SEITEN) + 1):
            if uhr() - start > BUDGET_S:
                gruende[s] = "Zeit abgelaufen, Rest ungeprüft"
                break
            muster = os.path.join(tmp, "r.pgm")
            subprocess.run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pgmraw", f"-r{DPI}",
                            "-dFILTERTEXT", "-dFILTERVECTOR", f"-dFirstPage={s}", f"-dLastPage={s}", "-o", muster, pfad],
                           check=True, capture_output=True, timeout=120)
            with open(muster, "rb") as f:
                w, h, pixel = L.pgm_lesen(f.read())
            os.remove(muster)
            ja, grund = seite_pruefen(w, h, pixel, sprache, tmp, lesen_)
            gruende[s] = grund
            if ja:
                kopf.append(s)
    return kopf, gruende


def drehen(pfad, kopf):
    """Set /Rotate +180 on the pages (in place, atomic). Returns an error text or None."""
    tmp = pfad + ".paperlaiss"
    r = L._qpdf("--deterministic-id", pfad, f"--rotate=+180:{','.join(map(str, kopf))}", "--", tmp)
    if r.returncode not in (0, 3) or not os.path.isfile(tmp):      # 3 = written with warnings
        if os.path.exists(tmp):
            os.remove(tmp)
        return f"qpdf: {r.stderr.strip()[:200]}"
    os.replace(tmp, pfad)
    return None


def ausrichten(pfad, lesen_=None):
    """Turn upside-down pages of the PDF (in place). Returns the message for the Paperless log."""
    grund = L.ausschluss(pfad)
    if grund:
        return f"unverändert ({grund})"
    seiten = int(L._qpdf("--show-npages", pfad).stdout.strip() or 0)
    if seiten < 1:
        return "unverändert (keine Seite)"
    kopf, gruende = kopfueber_seiten(pfad, seiten, sprachen(), lesen_)
    if not kopf:
        return f"keine Seite kopfüber ({seiten} Seiten: " + "; ".join(f"{s} {g}" for s, g in gruende.items())[:400] + ")"
    fehler = drehen(pfad, kopf)
    if fehler:
        return f"unverändert ({fehler})"
    return f"{len(kopf)} von {seiten} Seiten gedreht (180°): " + ", ".join(f"{s} ({gruende[s]})" for s in kopf)


def main():
    pfad = os.environ.get("DOCUMENT_WORKING_PATH") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not pfad or not os.path.isfile(pfad) or not L.ist_pdf(pfad):
        return 0
    if not einstellung(os.path.dirname(os.path.abspath(__file__))):
        return 0
    try:
        print("ausrichtung: " + ausrichten(pfad), flush=True)       # stdout: Paperless logs it as INFO
    except Exception as e:      # never hold up an import
        if os.path.exists(pfad + ".paperlaiss"):
            os.remove(pfad + ".paperlaiss")
        print(f"ausrichtung: Fehler, PDF bleibt unverändert: {e!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
