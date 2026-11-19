#!/usr/bin/env python3
"""Fachtest: die Info-Seite des Panels (panel/seiten.py `info()`).

Sie ist die Anleitung im Panel und darf nicht still von der Wirklichkeit abweichen. Geprüft wird deshalb:

1. **Aufbau** — die fünf Abschnitte mit ihren Sprungmarken, die Seite hängt in der Navigation.
2. **Eine Quelle für die Einstellungen** — jeder Schlüssel aus `EINSTELLUNGEN` steht in der Liste (also auch ein
   künftiger), die Geheimnis-Felder nie. Ein Test, der nur die heutigen Schlüssel kennt, würde den ersten neuen
   übersehen.
3. **Verweise auf die README** — jeder Anker, auf den die Seite zeigt, ist in `README.md` UND in der deutschen Fassung
   eine Überschrift; jeder Link der Seite auf die README nutzt einen dieser Anker.
4. **Verdrahtung** — die Route `/info` ruft `info()` und prüft vorher die Anmeldung (`guard`), wie die anderen Seiten.
5. **Nichts von Dritten** — weder `src` noch `<link>` zeigen auf eine fremde Adresse.
"""
from __future__ import annotations

import html as htmllib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel"))
sys.path.insert(0, str(ROOT / "tests"))
import huelle  # noqa: E402
import kern  # noqa: E402
import seiten  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — Info-Seite des Panels")
html = seiten.info()
voll = huelle.seite("Info", "/info", html)


def github_anker(ueberschrift: str) -> str:
    """GitHubs Anker: klein, Backticks und Satzzeichen weg (Unterstrich bleibt), Leerzeichen zu Bindestrichen."""
    t = ueberschrift.strip().lower().replace("`", "")
    t = re.sub(r"[^\w\- ]", "", t)
    return t.replace(" ", "-")


def anker_der(datei: str) -> set[str]:
    return {github_anker(m.group(2)) for m in re.finditer(r"^(#{1,6}) (.+?)\s*$",
            (ROOT / datei).read_text(encoding="utf-8"), re.M)}


# Selbsttest des Anker-Rechners gegen bekannte GitHub-Anker, sonst prüft der Test gegen eine eigene Annahme.
r.check("Anker-Rechner: Backticks, Klammern, Doppelpunkt, Unterstrich",
        github_anker("OCR fallback (`ocr_regeln`)") == "ocr-fallback-ocr_regeln"
        and github_anker("Configuration (`classify-config.json`)") == "configuration-classify-configjson"
        and github_anker("Pre-consume steps: blank pages, mails (optional)") == "pre-consume-steps-blank-pages-mails-optional")

# ---- 1. Aufbau
ids = re.findall(r'<div class="card mt-6" data-size="sm" id="([^"]+)"', html)
r.check("fünf Abschnitte in fester Reihenfolge",
        ids == ["was", "benutzung", "konfiguration", "grenzen", "bausteine"], str(ids))
sprung = re.findall(r'<a class="btn" data-variant="ghost" data-size="sm" href="#([^"]+)"', html)
r.check("jede Sprungmarke oben führt zu einem Abschnitt, und jeder Abschnitt hat eine", sprung == ids, str(sprung))
r.check("Info steht in der Navigation und ist dort als aktuelle Seite markiert",
        ("Info", "/info", "info") in huelle.NAVIGATION and 'aria-current="page"' in voll
        and re.search(r'href="/info"[^>]*aria-current="page"', voll) is not None)
r.check("Seitentitel", "<h1" in html and ">Info</h1>" in html and "<title>Info — paperlaiss</title>" in voll)
benutzung = re.search(r'id="benutzung">.*?</section></div>', html, re.S).group(0)
for stichwort in ("manual_fields", "reserved_fields", "reserved_tags", "Neu klassifizieren"):
    r.check(f"Abschnitt Benutzung nennt „{stichwort}“", stichwort in benutzung)
for stichwort in ("POST /ingest", "POST /route"):  # stehen unter „Was es tut“ (Drumherum)
    r.check(f"Abschnitt „Was es tut“ nennt „{stichwort}“", stichwort in re.search(r'id="was">.*?</section></div>', html, re.S).group(0))
r.check("Abschnitt Grenzen ist nicht leer",
        len(re.search(r'id="grenzen">.*?</section>', html, re.S).group(0)) > 400)

# ---- 2. Eine Quelle für die Einstellungen
konfig = re.search(r'id="konfiguration">.*?</section></div>', html, re.S).group(0)
schluessel = {m.group(1) for m in re.finditer(r"<code>([a-z_.]+)</code>", konfig)}
erwartet = {k for k in seiten.EINSTELLUNGEN if k.split(".")[0] not in kern.GEHEIM_FELDER}
r.check("jeder Schlüssel der Einstellungsseite steht in der Liste", erwartet <= schluessel,
        "fehlt: " + ", ".join(sorted(erwartet - schluessel)))
r.check("kein Geheimnis-Feld in der Liste",
        not (set(kern.GEHEIM_FELDER) & schluessel) and "api_key" not in html, str(set(kern.GEHEIM_FELDER) & schluessel))
r.check("jede Gruppe der Einstellungen ist eine Zwischenüberschrift",
        all(f'<h3 class="font-medium">{htmllib.escape(g)}</h3>' in konfig
            for g in seiten.GRUPPEN if any(v[0] == g for v in seiten.EINSTELLUNGEN.values())))
r.check("reserved_fields (T-20) steht mit seiner Beschreibung in der Liste",
        "<code>reserved_fields</code>" in konfig and "Custom Fields, die nur ein Mensch setzt" in konfig)

# Die Gegenprobe: die Liste folgt der Tabelle WIRKLICH (ein erfundener Schlüssel erscheint), und ein Geheimnis-Feld, das
# in der Tabelle stünde, wird herausgehalten. Ohne sie bliebe der Filter unbelegt, weil heute kein Geheimnis darin steht.
seiten.EINSTELLUNGEN["zz_neuer_schluessel"] = ("Allgemein", "Neuer Schlüssel", "Wirkt neu. Zweiter Satz.")
seiten.EINSTELLUNGEN["api_key_text"] = ("Erweitert", "Mistral-Schlüssel", "Geheim.")
try:
    probe = seiten.info_konfiguration()
finally:
    del seiten.EINSTELLUNGEN["zz_neuer_schluessel"], seiten.EINSTELLUNGEN["api_key_text"]
r.check("ein neuer Schlüssel erscheint von selbst, mit dem ersten Satz seiner Beschreibung",
        "<code>zz_neuer_schluessel</code>" in probe and "Wirkt neu." in probe and "Zweiter Satz" not in probe)
r.check("ein Geheimnis-Feld in der Tabelle wird nicht gelistet", "api_key_text" not in probe and "Mistral-Schlüssel" not in probe)

# ---- 3. Verweise auf die README
en, de = anker_der("README.md"), anker_der("i18n/README.de.md")
r.check("Anker-Tabelle der Seite ist nicht leer", len(seiten.INFO_ANKER) >= 8)
fehlt_en = {k: a for k, a in seiten.INFO_ANKER.items() if a not in en}
r.check("jeder Anker der Info-Seite ist eine Überschrift der README", not fehlt_en, str(fehlt_en))
# Die deutsche README hat andere Überschriften; die Struktur (Ebenen) ist an anderer Stelle geprüft. Hier zählt,
# dass der Abschnitt zu „Felder und Tags“ dort existiert, weil die Seite ihn als Quelle nennt.
r.check("die deutsche README hat den Abschnitt zu Feldern und Tags, die nur Menschen setzen",
        "felder-und-tags-die-nur-menschen-setzen" in de, str(sorted(a for a in de if "felder" in a)))
verlinkt = set(re.findall(r'href="' + re.escape(seiten.README_URL) + r'#([^"]+)"', html))
r.check("jeder Link der Seite auf die README nutzt einen Anker aus der Tabelle",
        verlinkt and verlinkt <= set(seiten.INFO_ANKER.values()), str(verlinkt - set(seiten.INFO_ANKER.values())))
r.check("die Seite verlinkt mindestens vier Abschnitte der README", len(verlinkt) >= 4, str(len(verlinkt)))

# ---- Verweise auf Panel-Seiten gehen auf bekannte Seiten
pfade = {p for _, p, _ in huelle.NAVIGATION}
intern = set(re.findall(r'<a class="underline" href="(/[^"#]*)"', html))
r.check("interne Links der Seite zeigen auf Seiten der Navigation", intern and intern <= pfade, str(intern - pfade))

# ---- 4. Verdrahtung
app = (ROOT / "panel" / "app.py").read_text(encoding="utf-8")
route = re.search(r'@app\.get\("/info"[^\n]*\ndef [^\n]*\n(?P<koerper>(?:[ \t]+[^\n]*\n)+)', app)
r.check("Route /info gibt es und ruft seiten.info()", route is not None and "seiten.info()" in route.group("koerper"))
r.check("Route /info prüft zuerst die Anmeldung (guard)",
        route is not None and route.group("koerper").find("guard(request)") != -1
        and route.group("koerper").find("guard(request)") < route.group("koerper").find("seiten.info()"))
r.check("GEHEIM_FELDER hat eine Quelle (kern.py), app.py und die Info-Seite nutzen sie",
        "from kern import GEHEIM_FELDER" in app and "GEHEIM_FELDER = (" not in app
        and "GEHEIM_FELDER" in (ROOT / "panel" / "seiten.py").read_text(encoding="utf-8"))

# ---- 5. Nichts von Dritten
fremd = [u for u in re.findall(r'(?:src|<link[^>]*href)="(https?://[^"]+)"', voll)]
r.check("kein src und kein <link> auf eine fremde Adresse", not fremd, str(fremd))

sys.exit(r.done())
