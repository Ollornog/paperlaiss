#!/usr/bin/env python3
"""Syntax des JavaScripts jeder Panel-Seite — mit `node --check`.

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
    for name in ("aktivitaet", "ablauf", "einstellungen"):
        html = getattr(seiten, name)()
        skripte = re.findall(r"<script>(.*?)</script>", html, re.S)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write("\n;\n".join(skripte))
        lauf = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        Path(f.name).unlink()
        r.check(f"Seite {name}: {len(skripte)} Skript(e), Syntax gültig",
                bool(skripte) and lauf.returncode == 0, lauf.stderr.strip()[:300])
sys.exit(r.done())
