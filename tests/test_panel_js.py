#!/usr/bin/env python3
"""Syntax des JavaScripts jeder Panel-Seite und des Knopf-Skripts für Paperless — mit `node --check`.

Die Seiten stehen als Python-Strings in `panel/seiten.py`; ein Fehler im JavaScript fällt
sonst erst im Browser auf, und dann nur als leere Seite. Genau das war die Falle beim ersten
Prompt-Vorschau-Bau: ein `\\n` im normalen Python-String wurde zum echten Zeilenumbruch und
zerbrach einen JS-String. Fehlt `node`, ist das ROT, nicht übersprungen — ein Test ohne seine
Voraussetzung darf nicht grün melden.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel"))
sys.path.insert(0, str(ROOT / "tests"))
import seiten  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — JavaScript der Panel-Seiten")
node = shutil.which("node")
r.check("node vorhanden (sonst ist dieser Test wertlos)", bool(node))
if node:
    for name in ("aktivitaet", "nacharbeit", "ablauf", "einstellungen"):
        html = getattr(seiten, name)()
        skripte = re.findall(r"<script>(.*?)</script>", html, re.S)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write("\n;\n".join(skripte))
        lauf = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        Path(f.name).unlink()
        r.check(f"Seite {name}: {len(skripte)} Skript(e), Syntax gültig",
                bool(skripte) and lauf.returncode == 0, lauf.stderr.strip()[:300])
    # Die Kette kommt als ol.flow aus C22: die Pfeile zeichnet das Stylesheet, ein Eintrag je Schritt.
    probe = (seiten._JS_GRUND + seiten._JS_SCHRITTE_FERTIG + """
;const html = kette([
  {art: 'grenze', ausloeser: []},
  {phase: 'A', art: 'code', titel: 'a1'}, {phase: 'A', art: 'code', titel: 'a2'},
  {phase: 'B', art: 'code', titel: 'b1'},
  {art: 'grenze', ende: true, titel: 'Ende'},
]);
const zahl = m => (html.match(m) || []).length;
console.log(JSON.stringify({listen: zahl(/<ol class="flow">/g), eintraege: zahl(/<li>/g), aussen: html.startsWith('<ol class="flow"><li>'), pfeile: zahl(/arrow-down/g)}));
""")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(probe)
    lauf = subprocess.run([node, f.name], capture_output=True, text=True)
    Path(f.name).unlink()
    kette = lauf.stdout.strip()
    # Außen 4 Einträge (Auslöser, A, B, Ende), innen 2 und 1; drei Listen.
    r.check("Ablauf: Kette ist ol.flow ohne eigene Pfeile",
            kette == '{"listen":3,"eintraege":7,"aussen":true,"pfeile":0}', kette or lauf.stderr.strip()[:300])
    # Das Knopf-Skript in Paperless (KI, Export, Korrespondenten-Abschnitt): reines JS ohne Bau,
    # ein Syntaxfehler nähme Paperless alle Knöpfe — Paperless selbst liefe weiter, still ohne sie.
    knoepfe = ROOT / "deploy" / "paperless-knoepfe" / "paperlaiss-knoepfe.js"
    lauf = subprocess.run([node, "--check", str(knoepfe)], capture_output=True, text=True)
    r.check("Knopf-Skript für Paperless: Syntax gültig", lauf.returncode == 0, lauf.stderr.strip()[:300])
sys.exit(r.done())
