#!/usr/bin/env python3
"""Browser-Test: der KI-Knopf im Korrespondenten-Dialog (T-15) in einem ECHTEN Chrome.

Gebaut wird eine Seite mit dem Aufbau des Paperless-Dialogs (`pngx-correspondent-edit-dialog`, ID-Plakette,
Formular), darin das echte Knopf-Skript `deploy/paperless-knoepfe/paperlaiss-knoepfe.js`; `fetch` antwortet
an Stelle des Panels. Ein Ablauf in der Seite klickt wie ein Mensch und schreibt am Ende, was er sah, als JSON
in den DOM; Chrome läuft headless mit virtueller Zeit (`--dump-dom`), also ohne Netz und ohne Wartezeit.

Geprüft: der Knopf ist da; vor dem Klick und vor „Übernehmen“ wird nichts gespeichert; die Vorschläge kommen
mit Haken, ein Ersatz eines schon gefüllten Werts ohne; abgehakte Werte bleiben draußen; „Übernehmen“ trägt
in Listen und Textfelder ein; erst „Save“ schickt sie ans Panel; ein Fehler des Panels wird angezeigt.

Fehlt Chrome, ist der Test ROT (nicht übersprungen): ein Test ohne seine Voraussetzung darf nicht grün melden.
`run_all.py --no-browser` lässt ihn in der kurzen Schleife weg.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel")); sys.path.insert(0, str(ROOT / "tests"))
from kern import KORR_FELDER  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Browser-Test — KI-Knopf im Korrespondenten-Dialog")
CHROME = next((shutil.which(b) for b in ("google-chrome", "chrome", "chromium", "chromium-browser") if shutil.which(b)), None)
r.check("Chrome vorhanden (sonst ist dieser Test wertlos)", bool(CHROME))
if not CHROME:
    sys.exit(r.done())

SKRIPT = (ROOT / "deploy/paperless-knoepfe/paperlaiss-knoepfe.js").read_text(encoding="utf-8").replace(
    "%%PAPERLAISS_URL%%", "/paperlaiss")
EINTRAG = {"felder": [list(f) for f in KORR_FELDER], "darf_aendern": True,
           "werte": {"aliase": ["Muster Vers."], "adresse": "Alte Straße 1, 20095 Hamburg", "kontext": "", "erfasst": {}}}
VORSCHLAG = {"korrespondent": "Muster Versicherung AG", "dokumente": 3, "verworfen": {},
             "vorschlag": {"iban": [{"wert": "DE02 1203 0000 0000 2020 51", "dokument": 11}],
                           "telefon": [{"wert": "040123456", "dokument": 11}],
                           "aliase": [{"wert": "Muster Vers.", "dokument": 12}, {"wert": "Muster Versicherungs-AG", "dokument": 12}],
                           "kontext": [{"wert": "Versicherer in Hamburg", "dokument": 11}],
                           "adresse": [{"wert": "Hauptstraße 5, 20095 Hamburg", "dokument": 11,
                                        "ersetzt": "Alte Straße 1, 20095 Hamburg"}]}}

SEITE = """<!doctype html><html><head><meta charset="utf-8"><title>t</title></head><body>
<pngx-correspondent-edit-dialog><form><div class="modal-header"><span class="badge">ID: 13</span></div>
<div class="modal-body"><input name="name" value="Muster Versicherung AG"></div>
<button type="submit">Save</button></form></pngx-correspondent-edit-dialog>
<pre id="ergebnis"></pre>
<script>
const EINTRAG = %(eintrag)s, VORSCHLAG = %(vorschlag)s, FEHLER = %(fehler)s;
const RUFE = [];
window.fetch = async (url, o) => {
  o = o || {};
  const pfad = String(url).replace(location.origin, "");
  RUFE.push({pfad, methode: o.method || "GET", rumpf: o.body ? JSON.parse(o.body) : null, kopf: o.headers || {}});
  const antwort = (status, daten) => ({ok: status < 400, status, json: async () => daten, text: async () => JSON.stringify(daten)});
  if (pfad === "/paperlaiss/knopf/korrespondent/13" && (o.method || "GET") === "GET") return antwort(200, EINTRAG);
  if (pfad === "/paperlaiss/knopf/korrespondent/13/vorschlag")
    return FEHLER ? antwort(502, {detail: "paperlaiss: Mistral nicht erreichbar"}) : antwort(200, VORSCHLAG);
  if (pfad === "/paperlaiss/knopf/korrespondent/13") return antwort(200, {ok: true});
  return antwort(404, {detail: "nicht da"});
};
</script>
<script>%(skript)s</script>
<script>
(async () => {
  const warte = async (f, ms) => { for (let i = 0; i < (ms || 3000) / 50; i++) { const x = f(); if (x) return x; await new Promise(z => setTimeout(z, 50)); } return null; };
  const e = {};
  const box = await warte(() => document.querySelector("pngx-correspondent-edit-dialog .paperlaiss-knoepfe"));
  const knopf = await warte(() => box && box.querySelector("[data-pl-ki]"));
  e.knopf = !!knopf && /Stammdaten/.test(knopf.textContent);
  e.speichern_vor_klick = RUFE.filter(x => x.methode === "POST").length;
  if (!knopf) { document.getElementById("ergebnis").textContent = JSON.stringify(e); return; }
  knopf.click();
  const haken = await warte(() => { const h = box.querySelectorAll("[data-pl-v-feld]"); return h.length ? h : null; });
  e.vorschlag_ruf = RUFE.filter(x => x.pfad.endsWith("/vorschlag")).map(x => ({methode: x.methode, kopf: x.kopf["X-Paperlaiss"]}));
  if (FEHLER) {
    await warte(() => box.querySelector("[data-pl-ki-erg] .text-danger"));
    e.fehler = (box.querySelector("[data-pl-ki-erg] .text-danger") || {}).textContent || "";
    e.knopf_wieder_frei = !knopf.disabled;
    document.getElementById("ergebnis").textContent = JSON.stringify(e); return;
  }
  e.haken = [...(haken || [])].map(h => [h.dataset.plVFeld, h.dataset.plVWert, h.checked]);
  e.speichern_vor_uebernehmen = RUFE.filter(x => x.methode === "POST" && !x.pfad.endsWith("/vorschlag")).length;
  e.liste_vor_uebernehmen = [...box.querySelectorAll('[data-pl-feld="iban"] [data-pl-wert]')].map(z => z.dataset.plWert);
  box.querySelector('[data-pl-v-feld="telefon"]').checked = false;            // der Mensch hakt einen ab
  box.querySelector("[data-pl-v-ok]").click();
  e.meldung = (box.querySelector("[data-pl-ki-erg]") || {}).textContent || "";
  const werte = f => [...box.querySelectorAll('[data-pl-feld="' + f + '"] [data-pl-wert]')].map(z => z.dataset.plWert);
  e.iban = werte("iban"); e.telefon = werte("telefon"); e.aliase = werte("aliase");
  e.kontext = box.querySelector('[data-pl="kontext"]').value;
  e.adresse = box.querySelector('[data-pl="adresse"]').value;
  e.speichern_nach_uebernehmen = RUFE.filter(x => x.methode === "POST" && !x.pfad.endsWith("/vorschlag")).length;
  document.querySelector("form").addEventListener("submit", ev => ev.preventDefault());
  document.querySelector("form").requestSubmit();
  await warte(() => RUFE.some(x => x.methode === "POST" && x.pfad === "/paperlaiss/knopf/korrespondent/13"));
  e.gespeichert = (RUFE.find(x => x.methode === "POST" && x.pfad === "/paperlaiss/knopf/korrespondent/13") || {}).rumpf;
  document.getElementById("ergebnis").textContent = JSON.stringify(e);
})().catch(err => { document.getElementById("ergebnis").textContent = JSON.stringify({ausnahme: String(err)}); });
</script></body></html>"""


def lauf(fehler=False):
    html = SEITE % {"eintrag": json.dumps(EINTRAG), "vorschlag": json.dumps(VORSCHLAG),
                    "fehler": "true" if fehler else "false", "skript": SKRIPT.replace("</script", "<\\/script")}
    with tempfile.TemporaryDirectory() as tmp:
        seite = Path(tmp) / "dialog.html"
        seite.write_text(html, encoding="utf-8")
        p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
                            "--disable-extensions", f"--user-data-dir={tmp}/profil", "--virtual-time-budget=20000",
                            "--dump-dom", seite.as_uri()], capture_output=True, text=True, timeout=120)
    roh = p.stdout.split('<pre id="ergebnis">', 1)[-1].split("</pre>", 1)[0]
    try:
        return json.loads(roh.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    except ValueError:
        return {"ausnahme": (roh or p.stderr)[-400:]}


e = lauf()
r.check("Knopf steht im Abschnitt, vor dem Klick wird nichts gespeichert", e.get("knopf") is True
        and e.get("speichern_vor_klick") == 0, json.dumps(e)[:400])
r.check("Klick fragt das Panel per POST mit dem eigenen Kopf (CORS-Schutz der Knöpfe)",
        e.get("vorschlag_ruf") == [{"methode": "POST", "kopf": "1"}], str(e.get("vorschlag_ruf")))
_h = {(f, w): c for f, w, c in e.get("haken", [])}
r.check("Vorschläge mit Haken; schon vorhandener Alias kommt nicht doppelt in die Liste; Ersatz der Adresse ohne Haken",
        _h.get(("iban", "DE02 1203 0000 0000 2020 51")) is True and _h.get(("adresse", "Hauptstraße 5, 20095 Hamburg")) is False
        and _h.get(("kontext", "Versicherer in Hamburg")) is True, str(e.get("haken")))
r.check("Vor „Übernehmen“: nichts gespeichert, Felder unverändert",
        e.get("speichern_vor_uebernehmen") == 0 and e.get("liste_vor_uebernehmen") == [])
r.check("„Übernehmen“ trägt Angehaktes ein (Liste, Textfeld), Abgehaktes und Ersatz ohne Haken nicht",
        e.get("iban") == ["DE02 1203 0000 0000 2020 51"] and e.get("telefon") == []
        and e.get("aliase") == ["Muster Vers.", "Muster Versicherungs-AG"] and e.get("kontext") == "Versicherer in Hamburg"
        and e.get("adresse") == "Alte Straße 1, 20095 Hamburg" and "eingetragen" in e.get("meldung", ""), json.dumps(e)[:600])
r.check("Erst „Save“ speichert — mit den übernommenen Werten",
        e.get("speichern_nach_uebernehmen") == 0 and (e.get("gespeichert") or {}).get("iban") == ["DE02 1203 0000 0000 2020 51"]
        and (e.get("gespeichert") or {}).get("kontext") == "Versicherer in Hamburg"
        and "040123456" not in (e.get("gespeichert") or {}).get("telefon", []), str(e.get("gespeichert")))
f = lauf(fehler=True)
r.check("Fehler des Panels wird im Dialog gezeigt, der Knopf ist wieder frei",
        "Mistral nicht erreichbar" in f.get("fehler", "") and f.get("knopf_wieder_frei") is True, json.dumps(f)[:400])
sys.exit(r.done())
