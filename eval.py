#!/usr/bin/env python3
"""Testsammlung (Eval): paperlaiss gegen eine Sollliste echter Dokumente laufen lassen.

Für jedes Dokument der Sollliste läuft classify.py im Trockenlauf (nichts wird geschrieben) und
das Ergebnis wird mit dem Soll verglichen: Korrespondent, Dokumenttyp, Datum. Mit --vergleich
zeigt der Bericht, was gegenüber einem früheren Lauf besser oder schlechter wurde; Rückschritte
geben Exit-Code 1. Die Sollliste gehört NICHT ins Repo (echte Dokumente), sondern neben die Config.

Sollliste (JSON): [{"id": 905, "korrespondent": "Häuser", "typ": "Erklaerung", "datum": "2026-08-16"}, …]
Ein fehlender Schlüssel wird nicht geprüft; "korrespondent": null heißt „keiner erwartet“.

Aufruf (wo classify.py und PAPERLESS_TOKEN/MISTRAL_KEY verfügbar sind, etwa im Panel-Container):
  python3 eval.py soll.json [--aus lauf.json] [--vergleich alter-lauf.json] [--parallel 2] [--mit-ocr]
"""
import argparse, concurrent.futures, json, os, re, subprocess, sys, unicodedata

FELDER = ("korrespondent", "typ", "datum")
HIER = os.path.dirname(os.path.abspath(__file__))


def falte(s):
    """Zum Vergleichen: klein, Umlaute als ae/oe/ue/ss, nur Buchstaben und Ziffern."""
    s = str(s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode())


def vergleiche(soll, ist):
    """Je geprüftem Feld: True (stimmt), False (falsch). Nicht im Soll → nicht geprüft."""
    erg = {}
    for f in FELDER:
        if f not in soll:
            continue
        s, i = soll[f], ist.get(f)
        erg[f] = (i in (None, "")) if s is None else (str(i or "")[:10] == str(s) if f == "datum" else falte(i) == falte(s))
    return erg


def lauf_auswerten(dry):
    """Aus der Trockenlauf-Ausgabe von classify.py das Ist."""
    return {"korrespondent": dry.get("korrespondent_ergebnis"), "typ": dry.get("document_type"),
            "datum": dry.get("document_date") or dry.get("datum_bisher")}   # kein neues Datum → das bisherige bleibt


def bericht(ergebnisse, alt=None):
    """Zusammenfassung: Trefferquote je Feld, Abweichungen, und gegenüber `alt` Verbesserungen/Rückschritte."""
    z = {f: [0, 0] for f in FELDER}
    abw, rueck, besser = [], [], []
    alt = {str(e["id"]): e for e in (alt or [])}
    for e in ergebnisse:
        for f, ok in e.get("vergleich", {}).items():
            z[f][0] += ok; z[f][1] += 1
            if not ok:
                abw.append(f"{e['id']} {f}: soll {e['soll'].get(f)!r}, ist {e['ist'].get(f)!r}")
            a = alt.get(str(e["id"]), {}).get("vergleich", {}).get(f)
            if a is True and not ok:
                rueck.append(f"{e['id']} {f}: war richtig, jetzt {e['ist'].get(f)!r}")
            elif a is False and ok:
                besser.append(f"{e['id']} {f}: jetzt richtig ({e['ist'].get(f)!r})")
    fehler = [f"{e['id']}: {e['fehler']}" for e in ergebnisse if e.get("fehler")]
    return {"quote": {f: f"{r}/{n}" for f, (r, n) in z.items()}, "abweichungen": abw,
            "rueckschritte": rueck, "verbesserungen": besser, "fehler": fehler}


def ein_lauf(eintrag, mit_ocr):
    env = {**os.environ, "CLASSIFY_DRY": "1", "CLASSIFY_FORCE": "1", "CLASSIFY_SOURCE": "manual",
           "CLASSIFY_DOC": str(eintrag["id"]), "CLASSIFY_LOG": os.environ.get("EVAL_LOG", "/tmp/paperlaiss-eval.log")}
    if not mit_ocr:
        env["CLASSIFY_NO_OCR"] = "1"
    out = subprocess.run([sys.executable, os.path.join(HIER, "classify.py")], env=env,
                         capture_output=True, text=True, timeout=900).stdout
    try:
        ist = lauf_auswerten(json.loads(out[out.index("{"):]))
    except Exception:
        return {"id": eintrag["id"], "soll": eintrag, "ist": {}, "vergleich": {}, "fehler": (out or "keine Ausgabe")[-200:]}
    return {"id": eintrag["id"], "soll": eintrag, "ist": ist, "vergleich": vergleiche(eintrag, ist)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("soll"); ap.add_argument("--aus"); ap.add_argument("--vergleich")
    ap.add_argument("--parallel", type=int, default=2); ap.add_argument("--mit-ocr", action="store_true")
    a = ap.parse_args(argv)
    soll = json.load(open(a.soll, encoding="utf-8"))
    with concurrent.futures.ThreadPoolExecutor(max(1, a.parallel)) as ex:
        ergebnisse = list(ex.map(lambda e: ein_lauf(e, a.mit_ocr), soll))
    if a.aus:
        json.dump(ergebnisse, open(a.aus, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    alt = json.load(open(a.vergleich, encoding="utf-8")) if a.vergleich else None
    b = bericht(ergebnisse, alt)
    print(json.dumps(b, ensure_ascii=False, indent=1))
    return 1 if b["rueckschritte"] else 0


if __name__ == "__main__":
    sys.exit(main())
