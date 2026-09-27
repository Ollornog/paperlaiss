#!/usr/bin/env python3
"""Wächter: jede Klasse und jede Variante im Panel muss es im vendorten C22-Stylesheet geben.

C22 kompiliert sein Tailwind gegen die *eigenen* Quellen. Eine Klasse, die dort nirgends
vorkommt, steht nicht im Pack und tut still nichts — kein Fehler, kein roter Test, nur eine
kaputte Seite. Das trifft nicht nur erfundene Namen (`btn-ghost`), sondern auch gültiges
Tailwind, das C22 selbst nicht benutzt (`py-12`). Deshalb mechanisch statt nach Gefühl:

1. **Klassen** — jedes `class="…"`-Token im Panel-Code existiert als Selektor im Pack.
2. **Varianten** — jeder `data-variant`/`data-size`-Wert existiert dort als Attributselektor.

Werte mit `{`/`}` (f-String, JS-Template) sind nicht auflösbar; sie werden gezählt, nicht
stillschweigend als geprüft verbucht. Muster: FleetCommander `tests/check_c22_klassen.py`.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from _kit.report import Report  # noqa: E402

STYLESHEET = ROOT / "panel" / "static" / "c22" / "css" / "c22.css"
# kern.py ausgenommen: sein Markup geht an die Anmeldeseite von TinySesam (brand_*), die nicht
# mit C22 gestaltet ist — dort gelten TinySesams eigene Klassen.
QUELLEN = sorted(p for p in (ROOT / "panel").glob("*.py") if p.name != "kern.py")
_KLASSE = re.compile(r'class="([^"]*)"')
_ATTRIBUT = re.compile(r'data-(variant|size)="([^"]*)"')


def bekannte_klassen(css: str) -> set[str]:
    # Das Pack ist minifiziert (eine Zeile) und escaped Sonderzeichen (`.sm\:grid-cols-2`):
    # über den ganzen Text suchen, Rückschrägstriche entfernen.
    return {m.group(1).replace("\\", "") for m in re.finditer(r"\.((?:[\w-]|\\.)+)", css)}


def bekannte_varianten(css: str) -> set[tuple[str, str]]:
    return {(m.group(1), m.group(2).strip("\"'"))
            for m in re.finditer(r"\[data-(variant|size)=([^\]]+)\]", css)}


def pruefe(quellen, css: str) -> tuple[list[str], int, int]:
    klassen, varianten = bekannte_klassen(css), bekannte_varianten(css)
    fehler, dynamisch, geprueft = [], 0, 0
    for pfad in quellen:
        for nr, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1):
            for t in _KLASSE.finditer(zeile):
                for token in t.group(1).split():
                    if any(z in token for z in "{}$+"):
                        dynamisch += 1
                        continue
                    geprueft += 1
                    if token not in klassen:
                        fehler.append(f"{pfad.name}:{nr}: Klasse '{token}' fehlt im C22-Pack")
            for t in _ATTRIBUT.finditer(zeile):
                art, wert = t.group(1), t.group(2)
                if any(z in wert for z in "{}$+"):
                    dynamisch += 1
                    continue
                geprueft += 1
                if (art, wert) not in varianten:
                    fehler.append(f'{pfad.name}:{nr}: data-{art}="{wert}" kennt C22 nicht')
    return fehler, dynamisch, geprueft


r = Report("Hygiene — C22-Klassen im Panel")

# Selbsttest: der Wächter muss genau die Fehler sehen, gegen die er gebaut ist.
_css = ".btn{}.card{}.sm\\:grid-cols-2{}[data-variant=ghost]{}[data-size=sm]{}"
_faelle = [('<a class="btn" data-variant="ghost">', 0), ('<a class="btn-ghost">', 1),
           ('<a class="btn sm:grid-cols-2">', 0), ('<a class="btn" data-variant="warn">', 1),
           ('<a class="py-12">', 1), ('<a class="${k}">', 0)]
with tempfile.TemporaryDirectory() as tmp:
    ok = True
    for i, (markup, erwartet) in enumerate(_faelle):
        p = Path(tmp) / f"f{i}.py"
        p.write_text(f"x = '{markup}'\n", encoding="utf-8")
        if len(pruefe([p], _css)[0]) != erwartet:
            ok = False
    r.check("Selbsttest: erfundene Klasse/Variante erkannt, gültige und dynamische nicht", ok)

r.check("vendortes C22-Stylesheet vorhanden (scripts/vendor-c22.sh)", STYLESHEET.is_file())
if STYLESHEET.is_file():
    _fehler, _dyn, _anzahl = pruefe(QUELLEN, STYLESHEET.read_text(encoding="utf-8"))
    # Null geprüfte Werte hieße: der Wächter sieht nichts und ist trotzdem grün.
    r.check(f"Panel-Code enthält C22-Markup ({_anzahl} Werte geprüft, {_dyn} dynamisch)", _anzahl > 20)
    r.check("jede Klasse und Variante gibt es im C22-Pack", not _fehler, "; ".join(_fehler[:12]))

# Varianten, die das JavaScript zur Laufzeit einsetzt (Badges je Ereignisart, Seitenknöpfe):
# im Code stehen sie nicht als data-variant="…", also hier gezielt gegen das Pack prüfen.
if STYLESHEET.is_file():
    sys.path.insert(0, str(ROOT / "panel"))
    import seiten  # noqa: E402
    _var = bekannte_varianten(STYLESHEET.read_text(encoding="utf-8"))
    _js = {v for *_, v in seiten.ARTEN} | {"outline", "ghost", "secondary", "warning", "info",
                                           "success", "destructive"}
    _fehlt = sorted(v for v in _js if ("variant", v) not in _var)
    r.check("jede zur Laufzeit gesetzte Variante gibt es im C22-Pack", not _fehlt, str(_fehlt))

sys.exit(r.done())
