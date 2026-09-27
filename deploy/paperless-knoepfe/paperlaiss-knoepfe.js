/*
 * paperlaiss — KI-Knopf in Paperless-ngx: optionaler Hinweis, dann liest paperlaiss das
 * Dokument per Mistral-OCR neu und klassifiziert es neu.
 *
 * Dokumentansicht: Knopf „KI" anstelle von Paperless' eigenem „Suggest" (ausgeblendet).
 * Dokumentliste:   Eintrag „KI" im Menü „Actions" der Mehrfachauswahl.
 *
 * Kein Fork: Paperless lädt diese Datei, weil ein Init-Skript sie beim Start einhängt
 * (10-paperlaiss-knoepfe.sh). Die Knöpfe rufen paperlaiss DIREKT (POST /knopf) — ohne Tag,
 * Hinweisfeld oder Workflow. Der Browser schickt die Paperless-Sitzung mit; paperlaiss fragt
 * damit bei Paperless nach, welche Dokumente dieser Nutzer ändern darf, und verarbeitet nur die.
 *
 * Ändert Paperless den Aufbau der Seite, fehlen die Knöpfe — Paperless selbst bleibt heil.
 * Icon: Bootstrap Icons „magic" (MIT, The Bootstrap Authors).
 */
(function () {
  "use strict";
  // Vom Init-Skript ersetzt (PAPERLAISS_URL): wo das Panel aus Sicht des Browsers liegt —
  // hinter demselben Proxy z. B. "/paperlaiss", im Testbett eine eigene Adresse mit Port.
  const PANEL = "%%PAPERLAISS_URL%%".replace(/\/$/, "");
  const MARKE = "paperlaiss-knoepfe";
  const ICON = {
    ki: '<svg width="1.2em" height="1.2em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M9.5 2.672a.5.5 0 1 0 1 0V.843a.5.5 0 0 0-1 0zm4.5.035A.5.5 0 0 0 13.293 2L12 3.293a.5.5 0 1 0 .707.707zM7.293 4A.5.5 0 1 0 8 3.293L6.707 2A.5.5 0 0 0 6 2.707zm-.621 2.5a.5.5 0 1 0 0-1H4.843a.5.5 0 1 0 0 1zm8.485 0a.5.5 0 1 0 0-1h-1.829a.5.5 0 0 0 0 1zM13.293 10A.5.5 0 1 0 14 9.293L12.707 8a.5.5 0 1 0-.707.707zM9.5 11.157a.5.5 0 0 0 1 0V9.328a.5.5 0 0 0-1 0zm1.854-5.097a.5.5 0 0 0 0-.706l-.708-.708a.5.5 0 0 0-.707 0L8.646 5.94a.5.5 0 0 0 0 .707l.708.708a.5.5 0 0 0 .707 0l1.293-1.293Zm-3 3a.5.5 0 0 0 0-.706l-.708-.708a.5.5 0 0 0-.707 0L.646 13.94a.5.5 0 0 0 0 .707l.708.708a.5.5 0 0 0 .707 0z"/></svg>',
  };

  function dokId() {
    const m = location.pathname.match(/\/documents\/(\d+)(\/|$)/);
    return m ? parseInt(m[1], 10) : null;
  }

  // Aufruf ans Panel: die Paperless-Sitzung geht mit (credentials), der eigene Kopf erzwingt
  // bei getrennten Adressen die CORS-Vorabfrage — nur freigegebene Paperless-Adressen bestehen.
  async function panel(pfad, daten) {
    const r = await fetch(PANEL + pfad, {
      method: daten ? "POST" : "GET",
      credentials: "include",
      headers: Object.assign({ "X-Paperlaiss": "1", Accept: "application/json" },
        daten ? { "Content-Type": "application/json" } : {}),
      body: daten ? JSON.stringify(daten) : undefined,
    });
    if (!r.ok) {
      let t = await r.text();
      try { t = JSON.parse(t).detail || t; } catch (e) { /* Text lassen */ }
      throw new Error(r.status + " " + String(t).slice(0, 200));
    }
    return r.json();
  }

  function meldung(text, art) {
    let el = document.getElementById(MARKE + "-meldung");
    if (!el) {
      el = document.createElement("div");
      el.id = MARKE + "-meldung";
      el.setAttribute("role", "status");
      el.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2000;max-width:380px";
      document.body.appendChild(el);
    }
    el.className = "alert shadow-sm mb-0 alert-" + (art || "info");
    el.textContent = text;
    if (art === "success") setTimeout(() => el.remove(), 5000);
  }

  // Wartet, bis paperlaiss alle Läufe beendet hat, und lädt dann neu — sonst speichert
  // Paperless beim nächsten „Speichern" seinen alten Stand über das Ergebnis.
  async function warten(ids, text) {
    for (let i = 0; i < 120; i++) {
      await new Promise((ok) => setTimeout(ok, 3000));
      let st;
      try { st = await panel("/knopf/status?docs=" + ids.join(",")); } catch (e) { continue; }
      const offen = ids.filter((d) => ["wartet", "laeuft"].includes(st[d]));
      const fehler = ids.filter((d) => st[d] === "fehler");
      meldung(`${text} — ${ids.length - offen.length} von ${ids.length} fertig` +
              (fehler.length ? `, ${fehler.length} mit Fehler` : "") + " …");
      if (!offen.length) {
        meldung(fehler.length ? `paperlaiss: ${fehler.length} Dokument(e) mit Fehler — Protokoll im Panel.`
                              : "paperlaiss ist fertig — lade neu …", fehler.length ? "warning" : "success");
        setTimeout(() => location.reload(), fehler.length ? 4000 : 900);
        return;
      }
    }
    meldung("paperlaiss antwortet nicht (Zeitüberschreitung). Panel und Protokoll prüfen.", "warning");
  }

  async function ausloesen(ids, hinweis) {
    const text = "paperlaiss klassifiziert neu (mit OCR)";
    try {
      const d = await panel("/knopf", { docs: ids, hinweis: hinweis || "" });
      if (d.verweigert.length) meldung(`paperlaiss: ${d.verweigert.length} Dokument(e) darfst du nicht ändern — übersprungen.`, "warning");
      if (!d.gestartet.length) return;
      meldung(text + " …");
      warten(d.gestartet, text);
    } catch (e) {
      meldung("paperlaiss: " + e.message, "danger");
    }
  }

  function dialogKi(anzahl, weiter) {
    const dlg = document.createElement("dialog");
    dlg.className = "p-0 border-0 rounded shadow";
    dlg.innerHTML =
      '<form method="dialog" class="card" style="min-width:min(520px,90vw)">' +
      '<div class="card-header">Mit paperlaiss neu klassifizieren' + (anzahl > 1 ? ` (${anzahl} Dokumente)` : "") + '</div>' +
      '<div class="card-body"><label class="form-label small">Hinweis für die KI (optional)</label>' +
      '<textarea class="form-control" rows="3" placeholder="z. B. Das ist eine Gutschrift, kein Rechnungseingang"></textarea>' +
      '<div class="form-text">Das Dokument wird per Mistral-OCR neu gelesen und neu klassifiziert.</div></div>' +
      '<div class="card-footer d-flex gap-2 justify-content-end">' +
      '<button value="nein" class="btn btn-sm btn-outline-secondary">Abbrechen</button>' +
      '<button value="ja" class="btn btn-sm btn-primary">Neu klassifizieren</button></div></form>';
    document.body.appendChild(dlg);
    dlg.addEventListener("close", () => {
      if (dlg.returnValue === "ja") weiter(dlg.querySelector("textarea").value.trim());
      dlg.remove();
    });
    dlg.showModal();
    dlg.querySelector("textarea").focus();
  }

  // ---------- Dokumentansicht ----------
  function knopf(icon, text, titel, aktion) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-sm btn-outline-primary";
    b.title = titel;
    b.innerHTML = icon + '<span class="d-none d-lg-inline ps-1">' + text + "</span>";
    b.addEventListener("click", aktion);
    return b;
  }

  function einfuegenDetail() {
    if (!dokId() || document.querySelector(".btn-group." + MARKE)) return;
    const zauberstab = document.querySelector("pngx-suggestions-dropdown");
    const gruppe = zauberstab && zauberstab.closest(".btn-group");
    if (!gruppe) return;
    const g = document.createElement("div");
    g.className = "btn-group " + MARKE;
    g.appendChild(knopf(ICON.ki, "KI", "paperlaiss: neu klassifizieren (optional mit Hinweis)",
      () => dialogKi(1, (h) => ausloesen([dokId()], h))));
    gruppe.after(g);
    gruppe.style.display = "none";   // Paperless' eigenes „Suggest" — paperlaiss ersetzt es
  }

  // ---------- Mehrfachauswahl: Einträge im Menü „Actions" ----------
  // Paperless hält die Auswahl nur im Speicher der App. Lesbar sind die angehakten Kästchen der
  // sichtbaren Seite (Tabelle: docCheck<id>, Karten: smallCardCheck<id>). Mit „Alle auswählen"
  // über mehrere Seiten sind mehr markiert als sichtbar — dann wird das offen gesagt.
  function auswahl() {
    return Array.from(document.querySelectorAll('input[id^="docCheck"]:checked, input[id^="smallCardCheck"]:checked'))
      .map((el) => parseInt(el.id.replace(/\D+/g, ""), 10)).filter((n) => n > 0);
  }

  function markiertLautPaperless() {
    const b = document.querySelector("pngx-document-list pngx-clearable-badge");
    const n = b ? parseInt((b.textContent || "").replace(/\D+/g, ""), 10) : NaN;
    return isNaN(n) ? null : n;
  }

  function mehrfach(weiter) {
    const ids = auswahl(), gesamt = markiertLautPaperless();
    if (!ids.length) { meldung("paperlaiss: keine sichtbaren Dokumente markiert.", "warning"); return; }
    if (gesamt !== null && gesamt > ids.length &&
        !confirm(`Markiert sind ${gesamt}, sichtbar sind ${ids.length}. paperlaiss verarbeitet nur die ` +
                 `${ids.length} sichtbaren. Fortfahren?`)) return;
    weiter(ids);
  }

  function menuEintrag(icon, text, aktion) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "dropdown-item " + MARKE;
    b.innerHTML = '<span class="me-1">' + icon + "</span>" + text;
    b.addEventListener("click", aktion);
    return b;
  }

  function einfuegenListe() {
    const knopfActions = document.querySelector("pngx-bulk-editor #dropdownSelect");
    const menu = knopfActions && knopfActions.parentElement.querySelector(".dropdown-menu");
    if (!menu || menu.querySelector("." + MARKE)) return;
    const trenner = document.createElement("div");
    trenner.className = "dropdown-divider " + MARKE;
    menu.appendChild(trenner);
    menu.appendChild(menuEintrag(ICON.ki, "KI", () =>
      mehrfach((ids) => dialogKi(ids.length, (h) => ausloesen(ids, h)))));
  }

  function alles() { einfuegenDetail(); einfuegenListe(); }
  new MutationObserver(alles).observe(document.documentElement, { childList: true, subtree: true });
  alles();
})();
