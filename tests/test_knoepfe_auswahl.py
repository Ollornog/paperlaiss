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
NACHFRAGEN = {"nachfragen": True, "anzahl": None}
FAELLE = [
    # (Name, Eingabe, erwartetes Ergebnis: Liste = ids, dict = genau so, None = Fehler)
    ("eine Seite, einzelne markiert", {"markiert": [3, 5], "sichtbar": SEITE, "gesamt": 2, "listen": [LISTE]}, [3, 5]),
    ("Befund 2026-10-01: Alles auswählen, 91 über zwei Seiten → Filter holen",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": 91, "listen": [LISTE]},
     {"abfrage": "tags__id__all=60&ordering=-created", "ausser": [], "anzahl": 91}),
    ("Alles auswählen, eines abgewählt → Paperless fragen",
     {"markiert": SEITE[1:], "sichtbar": SEITE, "gesamt": 90, "listen": [LISTE]}, {"nachfragen": True, "anzahl": 90}),
    ("Abwahl auf einer ANDEREN Seite (Zähler 90) → Paperless fragen, nicht 91 nehmen",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": 90, "listen": [LISTE]}, {"nachfragen": True, "anzahl": 90}),
    ("von Hand über zwei Seiten (2 sichtbar, 7 markiert) → Paperless fragen",
     {"markiert": [1, 2], "sichtbar": SEITE, "gesamt": 7, "listen": [LISTE]}, {"nachfragen": True, "anzahl": 7}),
    ("auf dieser Seite nichts, auf einer anderen 3 → Paperless fragen",
     {"markiert": [], "sichtbar": SEITE, "gesamt": 3, "listen": [LISTE]}, {"nachfragen": True, "anzahl": 3}),
    ("keine passende Listenantwort → Paperless fragen",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": 91, "listen": []}, {"nachfragen": True, "anzahl": 91}),
    ("Listenantwort einer anderen Seite (Dashboard) zählt nicht",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": 91,
      "listen": [{"seite": [1, 2], "abfrage": "", "anzahl": 91}]}, {"nachfragen": True, "anzahl": 91}),
    ("Zähler unlesbar, Liste hat nur eine Seite → sichtbare Auswahl",
     {"markiert": [4], "sichtbar": [4, 5], "gesamt": None, "listen": [{"seite": [4, 5], "abfrage": "", "anzahl": 2}]}, [4]),
    ("Zähler unlesbar, Liste hat mehrere Seiten → Paperless fragen",
     {"markiert": SEITE, "sichtbar": SEITE, "gesamt": None, "listen": [LISTE]}, NACHFRAGEN),
    ("nichts markiert → Fehler", {"markiert": [], "sichtbar": SEITE, "gesamt": 0, "listen": [LISTE]}, None),
]
# auswahlAusAnfrage(body, gesamt, ordnung): was Paperless an selection_data schickt
ANFRAGEN = [
    ("ID-Liste von Hand über Seiten", ({"documents": [7, 3, 99]}, 3, "-created"), [7, 3, 99]),
    ("ID-Liste passt nicht zum Zähler → Fehler", ({"documents": [7, 3]}, 3, ""), None),
    ("alle außer abgewählten, mit Sortierung der Liste",
     ({"all": True, "filters": {"tags__id__all": "60", "correspondent__id__in": [1, 2]}, "excluded_documents": [5]}, 90, "-created"),
     {"abfrage": "tags__id__all=60&correspondent__id__in=1%2C2&ordering=-created", "ausser": [5], "anzahl": 90}),
    ("eigene Sortierung in den Filtern bleibt",
     ({"all": True, "filters": {"ordering": "title"}, "excluded_documents": []}, 4, "-created"),
     {"abfrage": "ordering=title", "ausser": [], "anzahl": 4}),
    ("keine Anfrage gesehen → Fehler", (None, 3, ""), None),
    ("unbekannte Form → Fehler", ({"irgendwas": 1}, 3, ""), None),
]


def stimmt(ist, soll):
    if soll is None:
        return ist is not None and "fehler" in ist and len(ist) == 1 and len(ist["fehler"]) > 10
    if isinstance(soll, dict):
        return ist == soll
    return ist is not None and ist.get("ids") == soll and len(ist) == 1


if node and m:
    prog = m.group(1) + "\nconst f = " + json.dumps([f[1] for f in FAELLE]) + ";\n" \
        + "const a = " + json.dumps([list(f[1]) for f in ANFRAGEN]) + ";\n" \
        + "process.stdout.write(JSON.stringify([f.map(auswahlBestimmen), a.map((x) => auswahlAusAnfrage(...x))]));\n"
    lauf = subprocess.run([node, "-e", prog], capture_output=True, text=True)
    r.check("Auswahl-Logik läuft in node", lauf.returncode == 0, lauf.stderr.strip()[:300])
    erg_f, erg_a = json.loads(lauf.stdout) if lauf.returncode == 0 else ([], [])
    r.check("Auswahl: ein Ergebnis je Fall", len(erg_f) == len(FAELLE) and len(erg_a) == len(ANFRAGEN))
    for (name, _, soll), ist in zip(FAELLE, erg_f):
        r.check(f"Auswahl: {name}", stimmt(ist, soll), json.dumps(ist, ensure_ascii=False)[:200])
    for (name, _, soll), ist in zip(ANFRAGEN, erg_a):
        r.check(f"Paperless-Auswahl: {name}", stimmt(ist, soll), json.dumps(ist, ensure_ascii=False)[:200])

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
