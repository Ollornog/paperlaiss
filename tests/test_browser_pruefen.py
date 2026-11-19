#!/usr/bin/env python3
"""Browser-Test: die Seite „Prüfen“ und die Modell-Warnung der Einstellungen in einem ECHTEN Chrome (T-9 items 1, 7, 9).

Gebaut wird die vollständige Seite (`huelle.seite` + Inhalt aus `seiten`) mit dem vendorten C22-Stylesheet; `fetch`
antwortet an Stelle des Panels. Ein Ablauf in der Seite liest, was der Browser zeigt, klickt wie ein Mensch und
schreibt das Ergebnis als JSON in den DOM (headless Chrome `--dump-dom`, virtuelle Zeit, kein Netz).

Geprüft: markierte Dokumente stehen mit ihrem Grund in der Tabelle (ohne das Dokument zu öffnen); eine
wahrscheinlich eigene Kennung bietet „Als eigene übernehmen“ und „Nicht eigene“, eine schon eigene „Aus den
Stammdaten räumen“; der Klick schickt Feld, Wert und Aktion und lädt neu; ohne Prüf-Tag steht ein Hinweis da;
nichts kommt von fremder Herkunft. In den Einstellungen warnt ein „-latest“-Modell sichtbar mit Text, eine feste
Fassung nicht.

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
import seiten  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Browser-Test — Prüfen und Modell-Warnung")
CHROME = next((shutil.which(b) for b in ("google-chrome", "chrome", "chromium", "chromium-browser") if shutil.which(b)), None)
r.check("Chrome vorhanden (sonst ist dieser Test wertlos)", bool(CHROME))
if not CHROME:
    sys.exit(r.done())

PRUEFEN = {"tags": ["KI-unsicher"], "paperless": "https://paperless.example.com", "je_konto": False,
           "dokumente": [{"doc": 11, "titel": "Lohnabrechnung März", "korrespondent": "Muster GmbH", "typ": "Lohnabrechnung",
                          "lauf": "2026-11-18T10:00:00+00:00",
                          "gruende": [{"art": "eigene_person", "text": "Korrespondent ist eine eigene Person"},
                                      {"art": "datum", "text": "kein Datum im Text"}]},
                         {"doc": 12, "titel": "Scan", "korrespondent": "", "typ": "", "lauf": "",
                          "gruende": [{"art": "", "text": "kein Grund im Trace (von Hand markiert oder älterer Lauf)"}]}],
           "kennungen": [{"feld": "telefon", "wert": "+4930123456", "korrespondenten": 4, "dokumente": [11, 13],
                          "zuletzt": "2026-11-19", "bei": ["4"], "schon_eigen": False,
                          "grund": "steht auf Dokumenten von 4 Korrespondenten"},
                         {"feld": "iban", "wert": "DE02 1203 0000 0000 2020 51", "korrespondenten": None, "dokumente": [],
                          "zuletzt": None, "bei": ["3", "7"], "schon_eigen": True,
                          "grund": "schon eigene Kennung, steht aber noch in den Stammdaten"}]}
LEER = {"tags": [], "paperless": "", "je_konto": False, "dokumente": [], "kennungen": []}

ABLAUF_PRUEFEN = """<pre id="ergebnis"></pre><script>
const DATEN = %(daten)s, RUFE = [];
window.fetch = async (url, o) => {
  o = o || {}; const pfad = String(url).replace(location.origin, '');
  RUFE.push({pfad, methode: o.method || 'GET', rumpf: o.body ? JSON.parse(o.body) : null});
  const a = (s, d) => ({ok: s < 400, status: s, json: async () => d, text: async () => JSON.stringify(d)});
  if (pfad.endsWith('/api/pruefen')) return a(200, DATEN);
  if (pfad.endsWith('/api/pruefen/kennung')) return a(200, {ok: true, aus_stammdaten: ['4']});
  return a(404, {});
};
window.addEventListener('load', () => setTimeout(async () => {
  const e = {};
  const zeilen = [...document.querySelectorAll('#pr-doks tr[data-doc]')];
  e.doks = zeilen.map(z => z.dataset.doc);
  e.grund_11 = zeilen[0] ? zeilen[0].cells[1].textContent : '';
  e.link_11 = zeilen[0] ? zeilen[0].querySelector('a').getAttribute('href') : '';
  e.grund_12 = zeilen[1] ? zeilen[1].cells[1].textContent : '';
  e.leer_text = document.querySelector('#pr-doks td') ? document.querySelector('#pr-doks td').textContent : '';
  e.stand = document.getElementById('pr-stand').textContent;
  const k = [...document.querySelectorAll('#pr-kennungen tr[data-kennung]')];
  e.knoepfe = k.map(z => [...z.querySelectorAll('button')].map(b => b.dataset.aktion));
  e.bei = k.map(z => z.querySelector('[data-bei]').textContent);
  e.badge_abgesetzt = !!document.querySelector('#pr-doks .badge') &&
    getComputedStyle(document.querySelector('#pr-doks .badge')).borderStyle !== 'none';
  const gets = RUFE.filter(x => x.methode === 'GET').length;
  const b = k[0] && k[0].querySelector('button[data-aktion="uebernehmen"]');
  if (b) { b.click(); await new Promise(z => setTimeout(z, 300)); }
  e.post = RUFE.filter(x => x.methode === 'POST').map(x => [x.pfad.replace(/^.*\\/api/, '/api'), x.rumpf]);
  e.neu_geladen = RUFE.filter(x => x.methode === 'GET').length > gets;
  e.fremd = [...document.querySelectorAll('[src],link[href]')].map(x => x.getAttribute('src') || x.getAttribute('href'))
    .filter(u => /^(https?:)?\\/\\//.test(u));
  const d = document.documentElement; e.breite_ok = d.scrollWidth <= window.innerWidth;
  document.getElementById('ergebnis').textContent = JSON.stringify(e);
}, 400));
</script>"""

ABLAUF_EINSTELLUNGEN = """<pre id="ergebnis"></pre><script>
window.fetch = async (url) => ({ok: true, status: 200, json: async () => (%(cfg)s), text: async () => ''});
window.addEventListener('load', () => setTimeout(() => {
  const w = [...document.querySelectorAll('.alert[data-latest]')];
  document.getElementById('ergebnis').textContent = JSON.stringify({
    warnungen: w.map(x => x.dataset.latest), text: w.map(x => x.textContent),
    sichtbar: w.every(x => x.getBoundingClientRect().height > 0)});
}, 400));
</script>"""


def lauf(titel, pfad, inhalt, probe, breite=1280):
    seite = huelle.seite(titel, pfad, inhalt)
    statisch = (ROOT / "panel" / "static").as_uri()
    # Die Attrappe von fetch muss vor dem Skript der Seite stehen: es lädt sofort.
    seite = seite.replace('"/static/', f'"{statisch}/').replace("<main", probe + "<main", 1)
    with tempfile.TemporaryDirectory() as tmp:
        datei = Path(tmp) / "seite.html"
        datei.write_text(seite, encoding="utf-8")
        p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
                            "--allow-file-access-from-files", "--disable-extensions", f"--user-data-dir={tmp}/profil",
                            f"--window-size={breite},900", "--virtual-time-budget=20000", "--dump-dom", datei.as_uri()],
                           capture_output=True, text=True, timeout=120)
    roh = p.stdout.split('<pre id="ergebnis">', 1)[-1].split("</pre>", 1)[0]
    try:
        return json.loads(roh.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    except ValueError:
        return {"ausnahme": (roh or p.stderr)[-400:]}


e = lauf("Prüfen", "/pruefen", seiten.pruefen(), ABLAUF_PRUEFEN % {"daten": json.dumps(PRUEFEN)})
r.check("Prüfen: beide markierten Dokumente stehen in der Tabelle", e.get("doks") == ["11", "12"], json.dumps(e)[:400])
r.check("Prüfen: der Grund steht in der Zeile, beide Befunde, mit Art",
        "Korrespondent ist eine eigene Person" in e.get("grund_11", "") and "kein Datum im Text" in e["grund_11"]
        and "eigene_person" in e["grund_11"], e.get("grund_11"))
r.check("Prüfen: der Link führt zum Dokument in Paperless", e.get("link_11") == "https://paperless.example.com/documents/11/details")
r.check("Prüfen: ohne Grund im Trace steht das ausdrücklich da", "kein Grund im Trace" in e.get("grund_12", ""))
r.check("Prüfen: das C22-Stylesheet greift (Badge hat einen Rahmen)", e.get("badge_abgesetzt") is True)
r.check("Kennungen: Vorschlag → übernehmen oder verwerfen; schon eigen → räumen",
        e.get("knoepfe") == [["uebernehmen", "verwerfen"], ["raeumen"]], str(e.get("knoepfe")))
r.check("Kennungen: wo der Wert in den Stammdaten steht", e.get("bei") == ["in den Stammdaten bei #4", "in den Stammdaten bei #3, #7"], str(e.get("bei")))
r.check("Kennungen: der Klick schickt Feld, Wert und Aktion",
        e.get("post") == [["/api/pruefen/kennung", {"feld": "telefon", "wert": "+4930123456", "aktion": "uebernehmen"}]],
        str(e.get("post")))
r.check("Kennungen: danach wird neu geladen", e.get("neu_geladen") is True)
r.check("Prüfen: nichts von fremder Herkunft", e.get("fremd") == [], str(e.get("fremd")))
h = lauf("Prüfen", "/pruefen", seiten.pruefen(), ABLAUF_PRUEFEN % {"daten": json.dumps(PRUEFEN)}, breite=390)
r.check("Prüfen: auf Handybreite nicht breiter als das Fenster", h.get("breite_ok") is True, str(h)[:200])
l = lauf("Prüfen", "/pruefen", seiten.pruefen(), ABLAUF_PRUEFEN % {"daten": json.dumps(LEER)})
r.check("Prüfen: ohne Prüf-Tag ein Hinweis, keine leere Tabelle ohne Erklärung",
        "Kein Prüf-Tag eingerichtet" in l.get("stand", "") and "Keine markierten Dokumente" in l.get("leer_text", ""), str(l)[:300])

w = lauf("Einstellungen", "/einstellungen", seiten.einstellungen(),
         ABLAUF_EINSTELLUNGEN % {"cfg": json.dumps({"model": "mistral-small-latest", "ocr_model": "mistral-ocr-4-1"})})
r.check("Einstellungen: ein „-latest“-Modell wird sichtbar und mit Text gewarnt (nicht nur Farbe)",
        w.get("warnungen") == ["model"] and w.get("sichtbar") is True and "Achtung" in (w.get("text") or [""])[0], str(w))
w2 = lauf("Einstellungen", "/einstellungen", seiten.einstellungen(),
          ABLAUF_EINSTELLUNGEN % {"cfg": json.dumps({"model": "mistral-small-2603", "ocr_model": "mistral-ocr-4-1"})})
r.check("Einstellungen: feste Fassungen → keine Warnung", w2.get("warnungen") == [], str(w2))

sys.exit(r.done())
