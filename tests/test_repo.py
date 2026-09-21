#!/usr/bin/env python3
"""Hygiene: was man beim Aufräumen vergisst, prüft eine Maschine besser.

Pflichtdateien, Versionsgleichstand, keine Artefakte, keine Geheimnisse — und **keine
persönlichen Namen**: kein eigener Host, keine eigene Domain, kein Kundenname. Das Repo ist
öffentlich; die Regel darf nicht am Vorsatz hängen.

Die allgemeinen Prüfungen und die Sperrlisten stehen in `tests/_kit/` — einer geteilten,
eingecheckten Basis, die `repokit sync` hierher schreibt. Sie ist stdlib-only und lädt zur
Testzeit nichts nach. Was hier steht, gilt nur für dieses Projekt.
"""
from __future__ import annotations

import re
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subprocess  # noqa: E402
from _kit import backlog, hygiene  # noqa: E402
from _kit.report import Report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
r = Report("Hygiene — Repo")

POLICY = hygiene.lade_policy()
PROJEKTE = ["paperlaiss"]

DATEIEN = hygiene.getrackte_dateien(str(ROOT))
FILES = [ROOT / n for n in DATEIEN]


# ---- Pflichtdateien (zweisprachig, wo es den Leser betrifft)
PFLICHT = [
    "README.md", "i18n/README.de.md", "LICENSE", "CHANGELOG.md",
    "CONTRIBUTING.md", "i18n/CONTRIBUTING.de.md", "SECURITY.md", "i18n/SECURITY.de.md",
    "CODE_OF_CONDUCT.md", "i18n/CODE_OF_CONDUCT.de.md",
    "pyproject.toml", ".ci-image", ".gitignore",
    "classify.py", "classify-config.json",
    "panel/app.py", "panel/Dockerfile", "panel/requirements.txt",
    "deploy/.env.example", "deploy/docker-compose.example.yml",
    "scripts/check.sh", "scripts/_residue_check.sh", ".githooks/pre-push",
    ".github/workflows/ci.yml", ".github/workflows/release.yml", ".github/dependabot.yml",
    "tests/_kit/hygiene.py", "tests/_kit/backlog.py",
    "scripts/_backlog.py", "backlog/README-KONVENTION.md", "tests/run_all.py", "docs/paperlaiss.png",
]
fehlt = hygiene.pruefe_pflichtdateien(str(ROOT), PFLICHT)
r.check("alle Pflichtdateien vorhanden", not fehlt, " | ".join(fehlt))

# ---- Keine private Infrastruktur
# `admin@example.de` ist harmlos — `paperless.example.de` verrät, wo ein Paperless läuft.
# Muster und Sperrliste stehen in tests/_kit/hygiene_policy.json — einer Quelle für alle Repos.
treffer = hygiene.pruefe_private_infrastruktur(str(ROOT), DATEIEN, POLICY, PROJEKTE)
r.check(f"keine private Infrastruktur ({len(POLICY['private_muster'])} Muster"
        f" + {len(POLICY['private_namen_sha256_16'])} Namen)",
        not treffer, " | ".join(sorted(set(treffer))[:4]))

# ---- Nur neutrale Beispieladressen
# api.mistral.ai ist der echte LLM-Endpunkt, img.shields.io liefert die README-Badges,
# flaticon.com trägt den lizenzpflichtigen Bildnachweis fürs Logo —
# alles gehört zum Werkzeug, nicht zur privaten Infrastruktur.
adressen = hygiene.pruefe_adressen(str(ROOT), DATEIEN, POLICY,
                                   zusaetzliche_hosts=[r"mistral\.ai", r"img\.shields\.io",
                                                       r"(?:www\.)?flaticon\.com"])
r.check("nur neutrale Beispieladressen", not adressen, " | ".join(sorted(set(adressen))[:4]))

# ---- Keine Geheimnisse; Version steht überall gleich
lecks = hygiene.pruefe_geheimnisse(str(ROOT), DATEIEN, POLICY)
r.check("keine Geheimnisse im Klartext", not lecks, " | ".join(lecks[:3]))

pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M).group(1)
versionsfehler = hygiene.pruefe_versionsgleichstand(str(ROOT))
r.check(f"Version {version}: pyproject, CHANGELOG und SemVer stimmen",
        not versionsfehler, " | ".join(versionsfehler))

# ---- Keine Artefakte
artefakte = hygiene.pruefe_artefakte(DATEIEN, POLICY)
r.check("keine generierten Artefakte versioniert", not artefakte, " | ".join(artefakte[:3]))
r.check("keine .env versioniert", not [f for f in DATEIEN if Path(f).name == ".env"])
# Laufzeit-Ausgaben des Klassifizierers gehören nicht ins Repo.
r.check("kein classify.log versioniert", "classify.log" not in DATEIEN)
r.check("keine traces/ oder running/ versioniert",
        not [f for f in DATEIEN if f.startswith(("traces/", "running/"))])

# ---- Belegte Standards, maschinell erzwungen (context/repo-standards.md)
ungepinnt = hygiene.pruefe_actions_sha_gepinnt(str(ROOT), DATEIEN)
r.check("Actions per Commit-SHA gepinnt, nicht per Tag", not ungepinnt, " | ".join(ungepinnt[:3]))

ohne_rechte = hygiene.pruefe_workflow_permissions(str(ROOT), DATEIEN)
r.check("jeder Workflow setzt `permissions:`", not ohne_rechte, " | ".join(ohne_rechte[:3]))

runner = hygiene.pruefe_kein_self_hosted_runner(str(ROOT), DATEIEN)
r.check("kein self-hosted Runner (öffentliches Repo)", not runner, " | ".join(runner[:3]))

kategorien = hygiene.pruefe_changelog_kategorien(str(ROOT), POLICY)
r.check("CHANGELOG nutzt gültige Kategorien", not kategorien, " | ".join(kategorien[:2]))

uebersetzung = hygiene.pruefe_uebersetzungs_struktur(str(ROOT), [("README.md", "i18n/README.de.md")])
r.check("README.de.md folgt der Struktur von README.md", not uebersetzung, " | ".join(uebersetzung[:2]))

# ---- Der Klassifizierer bleibt stdlib-only und importierbar
classify = (ROOT / "classify.py").read_text(encoding="utf-8")
DRITTE = ("fastapi", "requests", "httpx", "uvicorn", "pydantic", "mistralai", "openai")
importe = re.findall(r"^\s*(?:import|from)\s+([a-zA-Z_][\w.]*)", classify, re.M)
fremd = sorted({i.split(".")[0] for i in importe} & set(DRITTE))
r.check("classify.py ist stdlib-only (keine Fremd-Importe)", not fremd, ", ".join(fremd))
r.check("classify.py ist importierbar (Ausführung nur unter __main__)",
        '__name__ == "__main__"' in classify or "__name__ == '__main__'" in classify)

# ---- Konfiguration und Secrets kommen aus der Umgebung, nicht aus Vorgabewerten
r.check("PAPERLESS_TOKEN kommt aus der Umgebung", 'os.environ.get("PAPERLESS_TOKEN"' in classify)
r.check("MISTRAL_KEY kommt aus der Umgebung", 'os.environ.get("MISTRAL_KEY"' in classify)
config = (ROOT / "classify-config.json").read_text(encoding="utf-8")
import json  # noqa: E402
cfg = json.loads(config)
r.check("classify-config.json trägt keine API-Schlüssel",
        not cfg.get("api_key_text") and not cfg.get("api_key_ocr"))

# ---- Release-Workflow: kein latest, Registry-Name kleingeschrieben, Tag geprüft
release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
r.check("kein latest-Tag im Release", ":latest" not in release)
tags_zeile = [ln for ln in release.splitlines() if ln.strip().startswith("tags:")]
r.check("repository_owner steht nicht in der tags-Zeile",
        not any("repository_owner" in ln for ln in tags_zeile), str(tags_zeile))
r.check("Release prüft den Tag gegen die Paketversion", "Tag und Paketversion" in release)
r.check("Release nutzt gh release create --verify-tag", "--verify-tag" in release)

# ---- Jede Suite läuft im Sammellauf mit
sammel = hygiene.pruefe_run_all_sammelt_automatisch(str(ROOT))
r.check("run_all.py findet die Suiten automatisch", not sammel, " | ".join(sammel))

# ---- Ausführbarkeit
nicht_x = hygiene.pruefe_ausfuehrbar(str(ROOT), ["scripts/check.sh", ".githooks/pre-push"])
r.check("scripts/check.sh und pre-push sind ausführbar", not nicht_x, " | ".join(nicht_x))

# ---- Backlog: Struktur, Verweise, generierter Index
for _v in backlog.alle_pruefungen(str(ROOT)):
    r.check(f"Backlog: {_v}", False)
r.check("Backlog hat Eintraege", bool(backlog.lade(str(ROOT))))
_idx = subprocess.run([sys.executable, "scripts/_backlog.py", "index", "--dry-run"],
                      cwd=ROOT, capture_output=True, text=True)
r.check("backlog/README.md ist aktuell (sonst: scripts/_backlog.py index)", _idx.returncode == 0)

# ---- Panel: Zusagen, die sich ohne FastAPI-Import statisch pruefen lassen.
# Am 2026-09-21 stand das Panel im Testbett ohne jede Anmeldung im LAN, weil guard()
# bei leerem PANEL_TOKEN einfach zurueckkehrte. Diese Pruefungen halten fest, dass die
# Schutzfunktion GESCHLOSSEN ausfaellt und dass keine Schluessel nach aussen gehen.
panel = (ROOT / "panel" / "app.py").read_text(encoding="utf-8")

r.check("guard() faellt geschlossen aus (kein stilles return bei leerem Token)",
        'if not PANEL_TOKEN:\n        if PANEL_AUTH == "none":' in panel
        and 'raise HTTPException(503' in panel)
r.check("Token-Vergleich ist laufzeitkonstant (hmac.compare_digest statt ==)",
        "hmac.compare_digest" in panel and 'auth == f"Bearer {PANEL_TOKEN}"' not in panel)
r.check("/api/config liefert keine Geheimnisfelder aus",
        "_cfg_oeffentlich()" in panel and "return _cfg()\n" not in panel)
r.check("/api/config nimmt keine Geheimnisfelder entgegen",
        "verboten = sorted(k for k in body if k in GEHEIM_FELDER)" in panel)
# Per AST statt per Textsuche: ein Docstring, der das schlechte Muster ZITIERT, ist kein
# Verstoss. Die erste Fassung dieser Pruefung schlug genau darauf an — Fehlalarm.
def _dump_in_open(quelle):
    """json.dump(..., open(...)) als AUFRUF finden, nicht als Text."""
    treffer = []
    for knoten in ast.walk(ast.parse(quelle)):
        if not isinstance(knoten, ast.Call):
            continue
        f = knoten.func
        if not (isinstance(f, ast.Attribute) and f.attr == "dump"
                and isinstance(f.value, ast.Name) and f.value.id == "json"):
            continue
        if len(knoten.args) >= 2 and isinstance(knoten.args[1], ast.Call) \
                and isinstance(knoten.args[1].func, ast.Name) and knoten.args[1].func.id == "open":
            treffer.append(knoten.lineno)
    return treffer


_dumps = _dump_in_open(panel)
r.check("JSON wird atomar geschrieben (kein truncate-dann-schreiben)",
        "def schreibe_json" in panel and "os.replace(tmp, pfad)" in panel and not _dumps,
        f"json.dump(..., open(...)) in Zeile {_dumps}" if _dumps else "")

# Der Generator haengte an einen Meilenstein ohne Aufgaben "— — erledigt" an: eine leere
# Quote plus das Wort "erledigt". Ein offener Meilenstein las sich damit als fertiger.
_bl = (ROOT / "backlog" / "README.md").read_text(encoding="utf-8")
r.check("Backlog-Index behauptet nichts Erledigtes ohne Aufgaben",
        "— — erledigt" not in _bl and "—  erledigt" not in _bl)
r.check("offene Meilensteine sind als offen erkennbar",
        all("☑" not in z for z in _bl.splitlines()
            if "M-1" in z and "offen" not in z.lower()) or "☐ **[M-1]" in _bl)

# Python meldet ungueltige Escape-Sequenzen (\d, \s in normalen Strings) nur als Warnung —
# sie verschwindet im Rauschen und die Datei laeuft trotzdem. In den HTML-Bloecken des Panels
# stehen JavaScript-Regexe, genau dort entsteht das leicht. Hier wird die Warnung zum Fehler.
import warnings as _warnings
_escape_fehler = []
for _py in sorted(ROOT.glob("*.py")) + sorted((ROOT / "panel").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py")):
    with _warnings.catch_warnings(record=True) as _w:
        _warnings.simplefilter("always")
        try:
            compile(_py.read_text(encoding="utf-8"), str(_py), "exec")
        except SyntaxError as _e:
            _escape_fehler.append(f"{_py.name}: {_e}")
            continue
        for _warnung in _w:
            if issubclass(_warnung.category, SyntaxWarning):
                _escape_fehler.append(f"{_py.relative_to(ROOT)}:{_warnung.lineno}: {_warnung.message}")
r.check("kein Python-Quelltext erzeugt SyntaxWarnings", not _escape_fehler, " | ".join(_escape_fehler[:3]))

sys.exit(r.done())
