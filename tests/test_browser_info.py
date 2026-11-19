#!/usr/bin/env python3
"""Browser-Test: die Info-Seite des Panels in einem ECHTEN Chrome, mit dem vendorten C22-Stylesheet.

Gebaut wird die vollständige Seite (`huelle.seite` + `seiten.info()`), ihre Adressen zeigen auf das vendorte
`panel/static/c22`. Ein Skript in der Seite liest, was der Browser daraus macht, und schreibt es als JSON in den DOM
(headless Chrome `--dump-dom`, virtuelle Zeit, kein Netz). Ein Test auf den HTML-Text allein sähe nicht, ob das
Stylesheet greift, ob die Tabellen Zeilen haben oder ob eine Sprungmarke ins Leere zeigt.

Geprüft: das Stylesheet greift (Abschnitte sind abgesetzte Karten, die aktive Navigation ist hinterlegt); jede
Sprungmarke trifft ein Element; die Konfigurationstabellen haben so viele Zeilen wie die Einstellungen Schlüssel;
kein Element lädt etwas von einer fremden Herkunft; die GANZE Seite (Titelleiste, Navigation und Inhalt) bricht auf Handybreite nicht
seitlich aus (Tabellen rollen in ihrem Bereich). Die Breite aller Panel-Seiten misst `tests/test_browser_breite.py`.

Fehlt Chrome, ist der Test ROT (nicht übersprungen). `run_all.py --no-browser` lässt ihn in der kurzen Schleife weg.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel")); sys.path.insert(0, str(ROOT / "tests"))
import huelle  # noqa: E402
import kern  # noqa: E402
import seiten  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Browser-Test — Info-Seite")
CHROME = next((shutil.which(b) for b in ("google-chrome", "chrome", "chromium", "chromium-browser") if shutil.which(b)), None)
r.check("Chrome vorhanden (sonst ist dieser Test wertlos)", bool(CHROME))
if not CHROME:
    sys.exit(r.done())

PROBE = """<pre id="ergebnis"></pre><script>
window.addEventListener('load', () => setTimeout(() => {
  const e = {};
  const karten = [...document.querySelectorAll('.card[id]')];
  e.karten = karten.map(k => k.id);
  // C22-Karten heben sich durch die Fläche ab (nicht durch einen Rand): ohne Stylesheet wäre sie dem Körper gleich.
  e.karte_abgesetzt = karten.length && getComputedStyle(karten[0]).backgroundColor !== getComputedStyle(document.body).backgroundColor;
  const aktiv = document.querySelector('nav[aria-label="Hauptbereiche"] [aria-current="page"]');
  e.aktiv = aktiv ? aktiv.textContent.trim() : null;
  e.aktiv_hintergrund = aktiv ? getComputedStyle(aktiv).backgroundColor : null;
  e.sprung_ohne_ziel = [...document.querySelectorAll('nav[aria-label="Abschnitte der Info-Seite"] a')]
    .filter(a => !document.getElementById(a.getAttribute('href').slice(1))).length;
  e.sprung = document.querySelectorAll('nav[aria-label="Abschnitte der Info-Seite"] a').length;
  e.konfig_zeilen = document.querySelectorAll('#konfiguration tbody tr').length;
  e.konfig_leer = [...document.querySelectorAll('#konfiguration tbody tr')].filter(t => !t.cells[0].textContent.trim() || !t.cells[2].textContent.trim()).length;
  e.fremd = [...document.querySelectorAll('[src],link[href]')].map(x => x.getAttribute('src') || x.getAttribute('href'))
    .filter(u => /^(https?:)?\\/\\//.test(u));
  e.ueberschriften = document.querySelectorAll('h1').length;
  // Die ganze Seite darf nicht breiter sein als ihr Fenster: Titelleiste mit Navigation UND Inhalt; eine Tabelle muss in
  // ihrem Rollbereich bleiben. (Bis 0.13.0 maß der Test nur `main`; die Titelleiste lief bei 500 px über, T-22.)
  // Jede Tabelle steht in einem Rollbereich: ein schmaler Schirm schneidet nichts ab und weitet die Seite nicht.
  e.tabellen = document.querySelectorAll('main table').length;
  e.tabellen_ohne_rollbereich = [...document.querySelectorAll('main table')]
    .filter(t => !['auto', 'scroll'].includes(getComputedStyle(t.parentElement).overflowX)).length;
  const d = document.documentElement;
  e.breite_ok = d.scrollWidth <= window.innerWidth;
  e.breite = [d.scrollWidth, window.innerWidth];
  const m = document.querySelector('main');
  e.inhalt_ok = m.scrollWidth <= m.clientWidth + 1;
  document.getElementById('ergebnis').textContent = JSON.stringify(e);
}, 300));
</script>"""


def lauf(breite):
    seite = huelle.seite("Info", "/info", seiten.info())
    statisch = (ROOT / "panel" / "static").as_uri()
    seite = seite.replace('"/static/', f'"{statisch}/').replace("</body>", PROBE + "</body>")
    with tempfile.TemporaryDirectory() as tmp:
        datei = Path(tmp) / "info.html"
        datei.write_text(seite, encoding="utf-8")
        p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--allow-file-access-from-files",
                            "--disable-extensions", f"--user-data-dir={tmp}/profil", f"--window-size={breite},900",
                            "--virtual-time-budget=20000", "--dump-dom", datei.as_uri()],
                           capture_output=True, text=True, timeout=120)
    roh = p.stdout.split('<pre id="ergebnis">', 1)[-1].split("</pre>", 1)[0]
    try:
        return json.loads(roh.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    except ValueError:
        return {"ausnahme": (roh or p.stderr)[-400:]}


e = lauf(1280)
r.check("fünf Abschnittskarten, und das C22-Stylesheet greift (Karte setzt sich vom Hintergrund ab)",
        e.get("karten") == ["was", "benutzung", "konfiguration", "grenzen", "bausteine"] and e.get("karte_abgesetzt") is True,
        json.dumps(e)[:300])
r.check("Navigation: „Info“ ist als aktuelle Seite markiert und hinterlegt",
        e.get("aktiv") == "Info" and e.get("aktiv_hintergrund") not in (None, "rgba(0, 0, 0, 0)", "transparent"),
        json.dumps(e)[:300])
r.check("jede Sprungmarke trifft einen Abschnitt", e.get("sprung") == 5 and e.get("sprung_ohne_ziel") == 0, json.dumps(e)[:300])
_erwartet = len([k for k in seiten.EINSTELLUNGEN if k.split(".")[0] not in kern.GEHEIM_FELDER])
r.check("die Konfigurationstabellen haben eine Zeile je Einstellung, keine ohne Schlüssel oder Wirkung",
        e.get("konfig_zeilen") == _erwartet and e.get("konfig_leer") == 0, f"{e.get('konfig_zeilen')} von {_erwartet}")
r.check("nichts wird von einer fremden Herkunft geladen", e.get("fremd") == [], str(e.get("fremd")))
r.check("genau eine Hauptüberschrift", e.get("ueberschriften") == 1)
h = lauf(390)
r.check("auf Handybreite bricht die ganze Seite nicht seitlich aus (Titelleiste, Navigation, Inhalt)",
        h.get("breite_ok") is True and h.get("inhalt_ok") is True, str(h.get("breite")))
r.check("jede Tabelle steht in einem Rollbereich",
        e.get("tabellen", 0) >= 5 and e.get("tabellen_ohne_rollbereich") == 0, f"{e.get('tabellen')} / ohne: {e.get('tabellen_ohne_rollbereich')}")

sys.exit(r.done())
