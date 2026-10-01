#!/usr/bin/env python3
"""Fachtest: welche Dokumente der Export- und KI-Knopf aus der Mehrfachauswahl nimmt, und wo das
Init-Skript das Knopf-Skript in Paperless einhängt.

Anlass (2026-10-01): von 91 markierten Dokumenten exportierte der Knopf still nur die 50 der
sichtbaren Seite. Die Entscheidung steht als reine Funktion `auswahlBestimmen` zwischen den Marken
`<auswahl-logik>` im Knopf-Skript; dieser Test führt sie mit node aus. Fehlt node, ist das ROT.

Das Init-Skript läuft echt gegen eine Attrappe der Paperless-Startseite: die Zeile muss im Kopf
stehen (vor Paperless' main.js, sonst verpasst das Mithören die erste Listenantwort), eine alte
Zeile vor </body> wird umgezogen, und ein zweiter Lauf ändert nichts.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — Auswahl der Knöpfe und Einhängen in Paperless")
KNOEPFE = ROOT / "deploy" / "paperless-knoepfe" / "paperlaiss-knoepfe.js"
INIT = ROOT / "deploy" / "paperless-knoepfe" / "10-paperlaiss-knoepfe.sh"

# ---- auswahlBestimmen() mit node
node = shutil.which("node")
r.check("node vorhanden (sonst ist dieser Test wertlos)", bool(node))
js = KNOEPFE.read_text(encoding="utf-8")
m = re.search(r"// <auswahl-logik>[^\n]*\n(.*?)// </auswahl-logik>", js, re.S)
r.check("Knopf-Skript: Auswahl-Logik zwischen den Marken gefunden", bool(m))

SEITE = list(range(1, 51))                 # 50 sichtbare Dokumente
LISTE = {"seite": SEITE, "abfrage": "tags__id__all=60&ordering=-created", "anzahl": 91}
FAELLE = [
    # (Name, Eingabe, erwartete IDs oder None für Fehler)
    ("eine Seite, einzelne markiert", {"markiert": [3, 5], "sichtbar": SEITE, "gesamt": 2, "listen": [LISTE]}, [3, 5]),
    ("Befund 2026-10-01: Alles auswählen, 91 über zwei Seiten → alle 91",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": 91, "listen": [LISTE]},
     {"alleSeiten": True, "abfrage": "tags__id__all=60&ordering=-created", "anzahl": 91}),
    ("Alles auswählen, aber eines auf der Seite abgewählt → Fehler statt raten",
     {"markiert": SEITE[1:], "sichtbar": SEITE, "gesamt": 90, "listen": [LISTE]}, None),
    ("Alles auswählen, Abwahl auf einer ANDEREN Seite (Zähler 90) → Fehler statt 91",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": 90, "listen": [LISTE]}, None),
    ("von Hand über zwei Seiten markiert (nur 2 sichtbar) → Fehler statt 2",
     {"markiert": [1, 2], "sichtbar": SEITE, "gesamt": 7, "listen": [LISTE]}, None),
    ("mehr markiert, aber keine passende Listenantwort → Fehler",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": 91, "listen": []}, None),
    ("Listenantwort einer anderen Seite (Dashboard) zählt nicht",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": 91,
      "listen": [{"seite": [1, 2], "abfrage": "", "anzahl": 91}]}, None),
    ("Zähler unlesbar, Liste hat nur eine Seite → sichtbare Auswahl",
     {"markiert": [4], "sichtbar": [4, 5], "gesamt": None, "listen": [{"seite": [4, 5], "abfrage": "", "anzahl": 2}]}, [4]),
    ("Zähler unlesbar, Liste hat mehrere Seiten → Fehler",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": None, "listen": [LISTE]}, None),
    ("Zähler unlesbar, keine Liste → Fehler",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": None, "listen": []}, None),
    ("nichts markiert → Fehler", {"markiert": [], "sichtbar": SEITE, "gesamt": 0, "listen": [LISTE]}, None),
]
if node and m:
    prog = m.group(1) + "\nconst f = " + json.dumps([f[1] for f in FAELLE]) + ";\n" \
        + "process.stdout.write(JSON.stringify(f.map(auswahlBestimmen)));\n"
    lauf = subprocess.run([node, "-e", prog], capture_output=True, text=True)
    r.check("Auswahl-Logik läuft in node", lauf.returncode == 0, lauf.stderr.strip()[:300])
    ergebnisse = json.loads(lauf.stdout or "[]") if lauf.returncode == 0 else []
    for (name, _, soll), ist in zip(FAELLE, ergebnisse + [None] * len(FAELLE)):
        ok = (ist is not None and "fehler" in ist and "ids" not in ist and "alleSeiten" not in ist) if soll is None \
            else (ist == soll) if isinstance(soll, dict) else (ist is not None and ist.get("ids") == soll)
        r.check(f"Auswahl: {name}", ok, json.dumps(ist, ensure_ascii=False)[:200])
    fehlertexte = [e.get("fehler", "") for e in ergebnisse]
    r.check("Auswahl: jede Fehlermeldung ist ein Satz für den Nutzer, nie leer",
            len(ergebnisse) == len(FAELLE)
            and all(len(t) > 10 for t, (_, _, soll) in zip(fehlertexte, FAELLE) if soll is None))

# ---- Init-Skript gegen eine Attrappe der Startseite
SEITE_HTML = """<!doctype html><html><head>
\t<title>Paperless</title>
</head>
<body>
\t<pngx-root></pngx-root>
\t<script src="{% static polyfills_js %}" type="module"></script>
\t<script src="{% static main_js %}" type="module"></script>
</body></html>
"""
ALT_ZEILE = "\t<script src=\"{% static 'paperlaiss-knoepfe.js' %}\" defer></script>\n"


def init_lauf(html):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "static").mkdir()
        (d / "index.html").write_text(html, encoding="utf-8")
        umg = dict(os.environ, PAPERLAISS_KNOEPFE_JS=str(KNOEPFE), PAPERLESS_STATICDIR=str(d / "static"),
                   PAPERLESS_INDEX_HTML=str(d / "index.html"), PAPERLAISS_URL="/paperlaiss")
        l1 = subprocess.run(["bash", str(INIT)], capture_output=True, text=True, env=umg)
        nach1 = (d / "index.html").read_text(encoding="utf-8")
        l2 = subprocess.run(["bash", str(INIT)], capture_output=True, text=True, env=umg)
        nach2 = (d / "index.html").read_text(encoding="utf-8")
        return l1, nach1, l2, nach2


def im_kopf(html):
    kopf = html.split("</head>", 1)[0]
    return html.count("paperlaiss-knoepfe.js") == 1 and "paperlaiss-knoepfe.js" in kopf \
        and html.index("paperlaiss-knoepfe.js") < html.index("main_js")


for name, html in (("frische Seite", SEITE_HTML),
                   ("alte Zeile vor </body> (bis 2026-10-01)", SEITE_HTML.replace("</body>", ALT_ZEILE + "</body>"))):
    l1, nach1, l2, nach2 = init_lauf(html)
    r.check(f"Init ({name}): endet mit 0", l1.returncode == 0 and l2.returncode == 0, l1.stdout + l1.stderr)
    r.check(f"Init ({name}): Zeile genau einmal, im Kopf, vor main.js", im_kopf(nach1), nach1)
    r.check(f"Init ({name}): zweiter Lauf ändert nichts", nach2 == nach1 and "schon eingehängt" in l2.stdout,
            l2.stdout)
sys.exit(r.done())
