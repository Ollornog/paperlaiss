#!/usr/bin/env python3
"""Browser-Test: jede Panel-Seite bleibt auf schmalem Schirm in der Fensterbreite (kein seitliches Scrollen).

Gebaut wird je Seite das vollständige Dokument (`huelle.seite` + Inhalt aus `seiten`) mit dem vendorten C22-Stylesheet.
Ein Skript in der Seite misst, was der Browser daraus macht, und schreibt es als JSON in den DOM (headless Chrome
`--dump-dom`, virtuelle Zeit, kein Netz). Gemessen wird die GANZE Seite, nicht nur der Inhaltsbereich:
`document.documentElement.scrollWidth <= innerWidth`. Der Fehler, den dieser Test festhält: die Titelleiste mit der
Navigation (gemeinsames Gerüst aller Seiten) lief bei 500 px seitlich über.

Zusätzlich: die Navigation umbricht auf Zeilen, statt abgeschnitten zu werden (jeder Punkt liegt im Fenster), und auf
Desktopbreite bleibt das Gerüst einzeilig (Logo, Navigation und Abmelden auf einer Höhe), das Layout ändert sich dort nicht.

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

r = Report("Browser-Test — Seitenbreite aller Panel-Seiten")
CHROME = next((shutil.which(b) for b in ("google-chrome", "chrome", "chromium", "chromium-browser") if shutil.which(b)), None)
r.check("Chrome vorhanden (sonst ist dieser Test wertlos)", bool(CHROME))
if not CHROME:
    sys.exit(r.done())

# Jede Seite des Panels (Pfad = Eintrag der Navigation) mit ihrem Inhalt.
SEITEN = {"/": ("Aktivität", seiten.aktivitaet), "/nacharbeit": ("Nacharbeit", seiten.nacharbeit),
          "/ablauf": ("Ablauf & Prompt", seiten.ablauf), "/einstellungen": ("Einstellungen", seiten.einstellungen),
          "/info": ("Info", seiten.info), "/pruefen": ("Prüfen", seiten.pruefen)}
r.check("jede Seite der Navigation wird gemessen", set(SEITEN) == {p for _, p, _ in huelle.NAVIGATION},
        str({p for _, p, _ in huelle.NAVIGATION} ^ set(SEITEN)))

PROBE = """<pre id="ergebnis"></pre><script>
window.addEventListener('load', () => setTimeout(() => {
  const e = {};
  const d = document.documentElement;
  e.breite = [d.scrollWidth, window.innerWidth];
  e.breite_ok = d.scrollWidth <= window.innerWidth;
  // Jeder Navigationspunkt und „Abmelden“ liegt ganz im Fenster (nichts rechts abgeschnitten).
  const teile = [...document.querySelectorAll('header a, header nav a')];
  e.draussen = teile.filter(a => a.getBoundingClientRect().right > window.innerWidth + 0.5 || a.getBoundingClientRect().left < -0.5)
    .map(a => a.textContent.trim());
  e.punkte = document.querySelectorAll('nav[aria-label="Hauptbereiche"] a').length;
  const kopf = document.querySelector('header');
  e.kopf_hoehe = Math.round(kopf.getBoundingClientRect().height);
  const oben = a => Math.round(a.getBoundingClientRect().top);
  const logo = kopf.querySelector('a[href]'); const nav = kopf.querySelector('nav a'); const raus = kopf.querySelector('a[href$="/auth/logout"]');
  e.einzeilig = oben(logo) === oben(nav) || Math.abs(oben(logo) - oben(nav)) <= 8;
  e.raus_einzeilig = !raus || Math.abs(oben(raus) - oben(nav)) <= 8;
  document.getElementById('ergebnis').textContent = JSON.stringify(e);
}, 300));
</script>"""


# Headless Chrome kennt eine Mindestbreite des Fensters (~500 px): schmalere Breiten misst der Test in einem iframe
# dieser Breite. Dessen Dokument ist ein eigenes Fenster mit eigenen Medienabfragen und eigenem `innerWidth`.
RAHMEN = """<!doctype html><meta charset="utf-8"><body style="margin:0"><pre id="ergebnis"></pre>
<iframe id="f" src="%(src)s" width="%(breite)d" height="900" style="border:0"></iframe><script>
document.getElementById('f').addEventListener('load', () => setTimeout(() => {
  const x = document.getElementById('f').contentDocument.getElementById('ergebnis');
  document.getElementById('ergebnis').textContent = x ? x.textContent : '';
}, 900));
</script>"""


def lauf(pfad, breite, abmelden=False):
    titel, inhalt = SEITEN[pfad]
    seite = huelle.seite(titel, pfad, inhalt(), abmelden=abmelden)
    statisch = (ROOT / "panel" / "static").as_uri()
    seite = seite.replace('"/static/', f'"{statisch}/').replace("</body>", PROBE + "</body>")
    with tempfile.TemporaryDirectory() as tmp:
        datei = Path(tmp) / "seite.html"
        datei.write_text(seite, encoding="utf-8")
        aussen = Path(tmp) / "rahmen.html"
        aussen.write_text(RAHMEN % {"src": datei.as_uri(), "breite": breite}, encoding="utf-8")
        p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--allow-file-access-from-files",
                            "--disable-extensions", f"--user-data-dir={tmp}/profil", "--window-size=1400,1000",
                            "--virtual-time-budget=20000", "--dump-dom", aussen.as_uri()],
                           capture_output=True, text=True, timeout=120)
    roh = p.stdout.split('<pre id="ergebnis">', 1)[-1].split("</pre>", 1)[0]
    try:
        return json.loads(roh.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    except ValueError:
        return {"ausnahme": (roh or p.stderr)[-400:]}


# Mit Abmelden-Knopf gemessen (der breiteste Fall der Titelleiste).
for breite in (500, 390, 360):
    for pfad in SEITEN:
        e = lauf(pfad, breite, abmelden=True)
        r.check(f"{pfad} bei {breite} px: Seite nicht breiter als das Fenster (scrollWidth ≤ innerWidth)",
                e.get("breite_ok") is True, str(e.get("breite") or e))
        r.check(f"{pfad} bei {breite} px: Navigation und Abmelden liegen ganz im Fenster",
                e.get("punkte") == len(huelle.NAVIGATION) and e.get("draussen") == [], str(e.get("draussen") or e))

# Desktop: das Gerüst bleibt einzeilig (kein Umbruch, keine Höhenänderung durch den Fix).
for pfad in SEITEN:
    e = lauf(pfad, 1280, abmelden=True)
    r.check(f"{pfad} bei 1280 px: Titelleiste einzeilig, Seite in der Fensterbreite",
            e.get("breite_ok") is True and e.get("einzeilig") is True and e.get("raus_einzeilig") is True, json.dumps(e)[:300])

sys.exit(r.done())
