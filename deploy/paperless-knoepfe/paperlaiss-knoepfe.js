/*
 * paperlaiss — KI-Knopf in Paperless-ngx: optionaler Hinweis, dann liest paperlaiss das
 * Dokument per Mistral-OCR neu und klassifiziert es neu.
 *
 * Dokumentansicht: Knopf „KI" anstelle von Paperless' eigenem „Suggest" (ausgeblendet).
 * Dokumentliste:   Einträge „KI" und „Export" im Menü „Actions" der Mehrfachauswahl. Export:
 *                  ein PDF (optional Seitenzahlen, Inhaltsverzeichnis) oder einzeln (Dateiname aus
 *                  Vorlage, Nummer, Sortierung, optional ZIP und Verzeichnis-PDF).
 * Korrespondent:   Abschnitt „paperlaiss" im Bearbeiten-Dialog — Kontext, Aliase, Domains usw.,
 *                  die der Klassifizierer beim Zuordnen nutzt; gespeichert mit „Save".
 *
 * Kein Fork: Paperless lädt diese Datei, weil ein Init-Skript sie beim Start einhängt
 * (10-paperlaiss-knoepfe.sh). Die Knöpfe rufen paperlaiss DIREKT (POST /knopf) — ohne Tag,
 * Hinweisfeld oder Workflow. Der Browser schickt die Paperless-Sitzung mit; paperlaiss fragt
 * damit bei Paperless nach, welche Dokumente dieser Nutzer ändern darf, und verarbeitet nur die.
 *
 * Ändert Paperless den Aufbau der Seite, fehlen die Knöpfe — Paperless selbst bleibt heil.
 * Icons: Bootstrap Icons „magic" und „download" (MIT, The Bootstrap Authors).
 */
(function () {
  "use strict";
  // Vom Init-Skript ersetzt (PAPERLAISS_URL): wo das Panel aus Sicht des Browsers liegt —
  // hinter demselben Proxy z. B. "/paperlaiss", im Testbett eine eigene Adresse mit Port.
  const PANEL = "%%PAPERLAISS_URL%%".replace(/\/$/, "");
  const MARKE = "paperlaiss-knoepfe";
  const ICON = {
    ki: '<svg width="1.2em" height="1.2em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M9.5 2.672a.5.5 0 1 0 1 0V.843a.5.5 0 0 0-1 0zm4.5.035A.5.5 0 0 0 13.293 2L12 3.293a.5.5 0 1 0 .707.707zM7.293 4A.5.5 0 1 0 8 3.293L6.707 2A.5.5 0 0 0 6 2.707zm-.621 2.5a.5.5 0 1 0 0-1H4.843a.5.5 0 1 0 0 1zm8.485 0a.5.5 0 1 0 0-1h-1.829a.5.5 0 0 0 0 1zM13.293 10A.5.5 0 1 0 14 9.293L12.707 8a.5.5 0 1 0-.707.707zM9.5 11.157a.5.5 0 0 0 1 0V9.328a.5.5 0 0 0-1 0zm1.854-5.097a.5.5 0 0 0 0-.706l-.708-.708a.5.5 0 0 0-.707 0L8.646 5.94a.5.5 0 0 0 0 .707l.708.708a.5.5 0 0 0 .707 0l1.293-1.293Zm-3 3a.5.5 0 0 0 0-.706l-.708-.708a.5.5 0 0 0-.707 0L.646 13.94a.5.5 0 0 0 0 .707l.708.708a.5.5 0 0 0 .707 0z"/></svg>',
    panel: '<svg width="1.2em" height="1.2em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8.636 3.5a.5.5 0 0 0-.5-.5H1.5A1.5 1.5 0 0 0 0 4.5v10A1.5 1.5 0 0 0 1.5 16h10a1.5 1.5 0 0 0 1.5-1.5V7.864a.5.5 0 0 0-1 0V14.5a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-10a.5.5 0 0 1 .5-.5h6.636a.5.5 0 0 0 .5-.5"/><path d="M16 .5a.5.5 0 0 0-.5-.5h-5a.5.5 0 0 0 0 1h3.793L6.146 9.146a.5.5 0 1 0 .708.708L15 1.707V5.5a.5.5 0 0 0 1 0z"/></svg>',
    plus: '<svg width="1em" height="1em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M8 2a.5.5 0 0 1 .5.5v5h5a.5.5 0 0 1 0 1h-5v5a.5.5 0 0 1-1 0v-5h-5a.5.5 0 0 1 0-1h5v-5A.5.5 0 0 1 8 2"/></svg>',
    stift: '<svg width="1em" height="1em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M12.146.146a.5.5 0 0 1 .708 0l3 3a.5.5 0 0 1 0 .708l-10 10a.5.5 0 0 1-.168.11l-5 2a.5.5 0 0 1-.65-.65l2-5a.5.5 0 0 1 .11-.168zM11.207 2.5 13.5 4.793 14.793 3.5 12.5 1.207zm1.586 3L10.5 3.207 4 9.707V10h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.293zm-9.761 5.175-.106.106-1.528 3.821 3.821-1.528.106-.106A.5.5 0 0 1 5 12.5V12h-.5a.5.5 0 0 1-.5-.5V11h-.5a.5.5 0 0 1-.468-.325"/></svg>',
    muell: '<svg width="1em" height="1em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5m2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5m3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0z"/><path d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4zM2.5 3h11V2h-11z"/></svg>',
    haken: '<svg width="1em" height="1em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M12.736 3.97a.733.733 0 0 1 1.047 0c.286.289.29.756.01 1.05L7.88 12.01a.733.733 0 0 1-1.065.02L3.217 8.384a.733.733 0 0 1 .01-1.05.733.733 0 0 1 1.047 0l3.052 3.093 5.4-6.425z"/></svg>',
    export: '<svg width="1.2em" height="1.2em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M.5 9.9a.5.5 0 0 1 .5.5v2.5a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-2.5a.5.5 0 0 1 1 0v2.5a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-2.5a.5.5 0 0 1 .5-.5"/><path d="M7.646 11.854a.5.5 0 0 0 .708 0l3-3a.5.5 0 0 0-.708-.708L8.5 10.293V1.5a.5.5 0 0 0-1 0v8.793L5.354 8.146a.5.5 0 1 0-.708.708z"/></svg>',
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

  // Fortschrittskarte unten rechts: Spinner, aktueller Schritt, Balken. Der Prozentwert kommt vom
  // Panel und schätzt nach der Reihenfolge der Schritte — keine gemessene Restzeit.
  function fortschritt(titel, schritt, prozent) {
    meldung("", "info");
    const el = document.getElementById(MARKE + "-meldung");
    el.innerHTML =
      '<div class="d-flex align-items-center gap-2"><span class="spinner-border spinner-border-sm" aria-hidden="true"></span>' +
      '<strong></strong></div><div class="small mt-1"></div>' +
      '<div class="progress mt-2" style="height:6px" role="progressbar"><div class="progress-bar progress-bar-striped progress-bar-animated"></div></div>';
    el.querySelector("strong").textContent = titel;
    el.querySelector(".small").textContent = schritt;
    const p = Math.max(3, Math.min(100, Math.round(prozent || 0)));
    el.querySelector(".progress-bar").style.width = p + "%";
    el.querySelector(".progress").setAttribute("aria-valuenow", String(p));
  }

  // Der KI-Knopf der Dokumentansicht: während eines Laufs gesperrt, mit Spinner — ein zweiter Klick
  // aus Ungeduld startet keinen zweiten Lauf (das Panel lehnt ihn ohnehin ab).
  const LAUFEND = new Set();
  function knopfBeschaeftigt(an) {
    const b = document.querySelector(".btn-group." + MARKE + " button");
    if (!b) return;
    b.disabled = an;
    b.innerHTML = an
      ? '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span class="d-none d-lg-inline ps-1">KI arbeitet …</span>'
      : ICON.ki + '<span class="d-none d-lg-inline ps-1">KI</span>';
  }

  const pause = (ms) => new Promise((ok) => setTimeout(ok, ms));

  // Wartet, bis paperlaiss alle Läufe beendet hat, und lädt dann neu — sonst speichert
  // Paperless beim nächsten „Speichern" seinen alten Stand über das Ergebnis.
  async function warten(ids, text) {
    ids.forEach((d) => LAUFEND.add(d));
    if (ids.includes(dokId())) knopfBeschaeftigt(true);
    for (let i = 0; i < 300; i++) {
      await pause(2000);
      let st;
      try { st = await panel("/knopf/status?docs=" + ids.join(",")); } catch (e) { continue; }
      const e = (d) => st[d] || { status: "unbekannt", schritt: "", prozent: 0 };
      const offen = ids.filter((d) => ["wartet", "laeuft"].includes(e(d).status));
      const fehler = ids.filter((d) => e(d).status === "fehler");
      if (offen.length) {
        const aktiv = offen.map(e).find((x) => x.status === "laeuft") || e(offen[0]);
        const prozent = ids.reduce((s, d) => s + (offen.includes(d) ? e(d).prozent || 0 : 100), 0) / ids.length;
        fortschritt(text, (ids.length > 1 ? `${ids.length - offen.length} von ${ids.length} fertig · ` : "") + aktiv.schritt, prozent);
        continue;
      }
      ids.forEach((d) => LAUFEND.delete(d));
      meldung(fehler.length ? `paperlaiss: ${fehler.length} Dokument(e) mit Fehler — Protokoll im Panel.`
                            : "paperlaiss ist fertig — lade neu …", fehler.length ? "warning" : "success");
      setTimeout(() => location.reload(), fehler.length ? 4000 : 900);
      return;
    }
    ids.forEach((d) => LAUFEND.delete(d));
    knopfBeschaeftigt(false);
    meldung("paperlaiss antwortet nicht (Zeitüberschreitung). Panel und Protokoll prüfen.", "warning");
  }

  async function ausloesen(ids, hinweis) {
    const text = "paperlaiss klassifiziert neu (mit OCR)";
    if (ids.includes(dokId())) knopfBeschaeftigt(true);
    fortschritt(text, "wird gestartet …", 2);
    try {
      const d = await panel("/knopf", { docs: ids, hinweis: hinweis || "" });
      const schon = d.laeuft_schon || [];
      const beobachten = d.gestartet.concat(schon);
      if (!beobachten.length) {
        knopfBeschaeftigt(false);
        meldung(d.verweigert.length ? `paperlaiss: ${d.verweigert.length} Dokument(e) darfst du nicht ändern.`
                                    : "paperlaiss: nichts zu tun.", "warning");
        return;
      }
      warten(beobachten, schon.length && !d.gestartet.length ? "paperlaiss arbeitet bereits daran" :
        text + (schon.length ? ` — ${schon.length} lief(en) schon` : "") +
        (d.verweigert.length ? ` — ${d.verweigert.length} ohne Recht übersprungen` : ""));
    } catch (e) {
      knopfBeschaeftigt(false);
      meldung("paperlaiss: " + e.message, "danger");
    }
  }

  // Beim Öffnen eines Dokuments: läuft schon ein KI-Lauf (anderer Tab, Seite neu geladen), sofort
  // sperren und den Fortschritt zeigen, statt einen zweiten Start zu erlauben.
  async function pruefeLaufend(id) {
    if (!id || LAUFEND.has(id)) return;
    try {
      const st = await panel("/knopf/status?docs=" + id);
      if (st[id] && ["wartet", "laeuft"].includes(st[id].status)) warten([id], "paperlaiss arbeitet an diesem Dokument");
    } catch (e) { /* ohne Panel keine Anzeige — der Knopf bleibt benutzbar */ }
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
    pruefeLaufend(dokId());
  }

  // ---------- Mehrfachauswahl: Einträge im Menü „Actions" ----------
  // Paperless hält die Auswahl nur im Speicher der App. Lesbar sind die angehakten Kästchen der
  // sichtbaren Seite (Tabelle: docCheck<id>, Karten: smallCardCheck<id>) und der Auswahlzähler.
  // Mit „Alles auswählen" über mehrere Seiten merkt sich Paperless 3 nur „alles, außer …" — die
  // IDs der anderen Seiten stehen nirgends im Browser. Deshalb hört das Skript die Listenabfragen
  // von Paperless mit (Filter, Sortierung, Anzahl, IDs der Seite) und holt bei „Alles auswählen"
  // die übrigen IDs mit genau diesen Filtern selbst. (`all` in der Antwort gibt es nur bis
  // API-Version 9, das Frontend fragt mit 10.) Befund 2026-10-01: ohne das exportierte der Knopf
  // von 91 markierten Dokumenten still nur die 50 der sichtbaren Seite.
  const LISTEN = [];        // die letzten Listenabfragen: {seite: [ids], abfrage: "filter=…", anzahl}
  const NICHT_FILTER = ["page", "page_size", "truncate_content", "include_selection_data", "fields", "format"];

  function listeMerken(url, text) {
    try {
      const u = new URL(url, location.href);
      if (!/\/api\/documents\/?$/.test(u.pathname) || !u.searchParams.has("page")) return;
      const j = typeof text === "string" ? JSON.parse(text) : text;
      if (!j || typeof j.count !== "number" || !Array.isArray(j.results)) return;
      NICHT_FILTER.forEach((k) => u.searchParams.delete(k));
      LISTEN.unshift({ seite: j.results.map((d) => d.id), abfrage: u.searchParams.toString(), anzahl: j.count });
      LISTEN.length = Math.min(LISTEN.length, 5);
    } catch (e) { /* keine Liste — nichts merken */ }
  }

  // Alle IDs einer gemerkten Abfrage, in ihrer Sortierung — mit der Sitzung des Nutzers, also nur,
  // was er sehen darf. Seitenweise, damit auch eine große Auswahl keine Riesenantwort braucht.
  async function alleIds(abfrage) {
    const ids = [];
    for (let seite = 1; seite <= 100; seite++) {
      const u = new URL("api/documents/", document.baseURI);
      u.search = abfrage;
      u.searchParams.set("fields", "id");
      u.searchParams.set("page_size", "500");
      u.searchParams.set("page", String(seite));
      const r = await fetch(u.href, { credentials: "include", headers: { Accept: "application/json" } });
      if (!r.ok) throw new Error("Paperless antwortet " + r.status);
      const j = await r.json();
      (j.results || []).forEach((d) => ids.push(d.id));
      if (!j.next) return ids;
    }
    throw new Error("Auswahl zu groß");
  }

  // Mithören, ohne Paperless zu stören: jede Ausnahme hier bleibt hier.
  (function mithoeren() {
    const X = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
    if (X && !X.__paperlaiss) {
      X.__paperlaiss = true;
      const open = X.open, send = X.send;
      X.open = function (methode, url) { this.__plUrl = String(url); return open.apply(this, arguments); };
      X.send = function () {
        if (this.__plUrl && this.__plUrl.indexOf("documents") >= 0) {
          this.addEventListener("load", () => {
            try {
              const t = this.responseType === "json" ? this.response
                : (this.responseType === "" || this.responseType === "text") ? this.responseText : null;
              if (t) listeMerken(this.responseURL || this.__plUrl, t);
            } catch (e) { /* nichts */ }
          });
        }
        return send.apply(this, arguments);
      };
    }
    if (window.fetch && !window.fetch.__paperlaiss) {
      const f = window.fetch;
      const neu = function (eingabe) {
        const p = f.apply(this, arguments);
        try {
          const url = typeof eingabe === "string" ? eingabe : (eingabe && eingabe.url) || "";
          if (url.indexOf("documents") >= 0) {
            p.then((r) => r.clone().text().then((t) => listeMerken(r.url || url, t))).catch(() => {});
          }
        } catch (e) { /* nichts */ }
        return p;
      };
      neu.__paperlaiss = true;
      window.fetch = neu;
    }
  })();

  // <auswahl-logik> — rein, ohne DOM; tests/test_knoepfe_auswahl.py prüft sie mit node.
  // e = {markiert: [ids angehakt, sichtbar], sichtbar: [ids der Seite], gesamt: Zähler von Paperless
  // oder null, listen: [{seite, abfrage, anzahl}]}. Ergebnis: {ids}, {alleSeiten, abfrage, anzahl}
  // (IDs holt alleIds) oder {fehler}. Nie still kürzen.
  function auswahlBestimmen(e) {
    const markiert = e.markiert || [], sichtbar = e.sichtbar || [];
    const gesamt = typeof e.gesamt === "number" && e.gesamt >= 0 ? e.gesamt : null;
    const gleich = (a, b) => a.length === b.length && a.every((x) => b.indexOf(x) >= 0);
    const liste = (e.listen || []).find((l) => gleich(l.seite, sichtbar)) || null;
    const mehrSeiten = liste ? liste.anzahl > sichtbar.length : null;
    if (gesamt === null) {
      // Zähler nicht gefunden: der sichtbaren Auswahl nur trauen, wenn es keine weiteren Seiten gibt.
      if (!markiert.length) return { fehler: "keine Dokumente markiert" };
      if (mehrSeiten === false) return { ids: markiert };
      return { fehler: "Paperless zeigt nicht an, wie viele Dokumente markiert sind, und die Liste hat " +
        "mehrere Seiten — die Auswahl lässt sich nicht sicher bestimmen. Seite neu laden und erneut versuchen." };
    }
    if (gesamt === 0 || (!markiert.length && !mehrSeiten)) return { fehler: "keine Dokumente markiert" };
    if (gesamt === markiert.length) return { ids: markiert };
    if (gesamt > markiert.length && liste && markiert.length === sichtbar.length && gesamt === liste.anzahl) {
      return { alleSeiten: true, abfrage: liste.abfrage, anzahl: gesamt };   // „Alles auswählen", nichts abgewählt
    }
    if (!liste) {
      return { fehler: `Markiert sind ${gesamt}, auf dieser Seite sichtbar ${markiert.length} — die übrigen ` +
        "kann paperlaiss gerade nicht lesen. Seite neu laden und erneut versuchen." };
    }
    return { fehler: `Markiert sind ${gesamt}, auf dieser Seite sichtbar ${markiert.length}. Über mehrere Seiten ` +
      "geht der Export nur mit „Alles auswählen“ ohne einzelne Abwahl — sonst die Seitengröße erhöhen, " +
      "bis alle markierten auf einer Seite stehen." };
  }
  // </auswahl-logik>

  function sichtbareKaestchen() {
    return Array.from(document.querySelectorAll('input[id^="docCheck"], input[id^="smallCardCheck"]'))
      .map((el) => ({ id: parseInt(el.id.replace(/\D+/g, ""), 10), an: el.checked })).filter((k) => k.id > 0);
  }

  // Der Auswahlzähler („× 91") — ein clearable-badge der Dokumentliste, aber NICHT eines der
  // Filter-Menüs (die tragen dasselbe Element; bis 2026-10-01 griff der Selektor eines davon).
  function markiertLautPaperless() {
    const b = Array.from(document.querySelectorAll("pngx-document-list pngx-clearable-badge"))
      .find((el) => !el.closest("pngx-filter-editor, pngx-filterable-dropdown, pngx-bulk-editor, .dropdown-menu"));
    const n = b ? parseInt((b.textContent || "").replace(/\D+/g, ""), 10) : NaN;
    return isNaN(n) ? null : n;
  }

  let auswahlLaeuft = false;      // Reklick auf den Menüeintrag, während die Auswahl gelesen wird
  async function mehrfach(weiter) {
    if (auswahlLaeuft) return;
    const k = sichtbareKaestchen();
    const a = auswahlBestimmen({ markiert: k.filter((x) => x.an).map((x) => x.id), sichtbar: k.map((x) => x.id),
      gesamt: markiertLautPaperless(), listen: LISTEN });
    if (a.fehler) { meldung("paperlaiss: " + a.fehler, "warning"); return; }
    if (!a.alleSeiten) { weiter(a.ids); return; }
    auswahlLaeuft = true;
    let ids;
    try {
      meldung(`paperlaiss: Auswahl über alle Seiten wird gelesen (${a.anzahl} Dokumente) …`, "info");
      ids = await alleIds(a.abfrage);
    } catch (e) {
      meldung("paperlaiss: Auswahl nicht lesbar — " + e.message, "danger");
      return;
    } finally { auswahlLaeuft = false; }
    if (ids.length !== a.anzahl) {
      meldung(`paperlaiss: Markiert sind ${a.anzahl}, Paperless liefert für diesen Filter jetzt ${ids.length} — ` +
              "die Liste hat sich geändert. Seite neu laden und erneut auswählen.", "warning");
      return;
    }
    const m = document.getElementById(MARKE + "-meldung");
    if (m) m.remove();
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
    menu.appendChild(menuEintrag(ICON.export, "Export", () => mehrfach(dialogExport)));
  }

  // ---------- Export: ein PDF oder einzeln (optional ZIP), mit Inhaltsverzeichnis ----------
  // Der Dialog fragt das Panel nach Variablen und Feldern, startet den Export als Auftrag, zeigt den
  // Stand und lädt das Ergebnis herunter — per fetch mit dem eigenen Kopf, nicht per Link, damit
  // auch der Download dieselbe Prüfung durchläuft wie jeder Knopf-Aufruf.
  const esc = (v) => String(v == null ? "" : v).replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));

  function groesse(b) {
    return b >= 1048576 ? (b / 1048576).toFixed(1).replace(".", ",") + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
  }

  // Wo Paperless liegt (für die Links im Inhaltsverzeichnis): <base href> berücksichtigt einen
  // Unterpfad. Das Panel nimmt den Wert nur vom selben Ursprung wie die Anfrage an.
  function paperlessBasis() {
    const b = document.querySelector("base");
    return new URL((b && b.getAttribute("href")) || "/", location.href).href;
  }

  // Lädt eine fertige Datei und meldet den Fortschritt (0–100, oder null ohne Content-Length).
  async function herunterladen(job, nr, name, fortschritt) {
    const r = await fetch(PANEL + "/knopf/export/" + encodeURIComponent(job) + "/datei/" + nr,
      { credentials: "include", headers: { "X-Paperlaiss": "1" } });
    if (!r.ok) {
      let t = await r.text();
      try { t = JSON.parse(t).detail || t; } catch (e) { /* Text lassen */ }
      throw new Error(r.status + " " + String(t).slice(0, 200));
    }
    let blob;
    const laenge = parseInt(r.headers.get("Content-Length") || "", 10);
    if (r.body && r.body.getReader && fortschritt) {
      const leser = r.body.getReader(), teile = [];
      let da = 0;
      for (;;) {
        const { done, value } = await leser.read();
        if (done) break;
        teile.push(value);
        da += value.length;
        fortschritt(laenge > 0 ? Math.min(100, Math.round(100 * da / laenge)) : null, da);
      }
      blob = new Blob(teile, { type: r.headers.get("Content-Type") || "application/octet-stream" });
    } else {
      blob = await r.blob();
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  // Reklick-Schutz: es gibt höchstens EINEN Export-Dialog. Ein zweiter Klick auf „Export" holt den
  // offenen nach vorn, statt einen zweiten Export anzustoßen.
  let exportDialogOeffnet = false;
  async function dialogExport(ids) {
    const offen = document.querySelector("dialog." + MARKE + "-export");
    if (offen) { if (!offen.open) offen.showModal(); offen.focus(); return; }
    if (exportDialogOeffnet) return;
    exportDialogOeffnet = true;
    let opt;
    try {
      meldung("paperlaiss: Export-Dialog wird geladen …", "info");
      opt = await panel("/knopf/export/optionen");
      const m = document.getElementById(MARKE + "-meldung");
      if (m) m.remove();
    } catch (e) { meldung("paperlaiss: " + e.message, "danger"); return; }
    finally { exportDialogOeffnet = false; }
    if (ids.length > opt.grenzen.dokumente) {
      meldung(`paperlaiss: höchstens ${opt.grenzen.dokumente} Dokumente je Export — markiert sind ${ids.length}.`, "warning");
      return;
    }
    const chip = (v, titel) => '<button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1 me-1 mb-1" data-var="' +
      esc(v) + '" title="' + esc(titel) + '">' + esc(v) + "</button>";
    const variablen = opt.variablen.map(([n, t]) => chip("{" + n + "}", t)).join("") +
      opt.felder.map((f) => chip("{feld:" + f + "}", "Benutzerdefiniertes Feld")).join("");
    const sortierbar = opt.variablen.filter(([n]) => !["jahr", "monat", "original"].includes(n));
    const sortierung = '<option value="">wie ausgewählt</option>' +
      sortierbar.map(([n, t]) => '<option value="' + esc(n) + '">' + esc(t) + "</option>").join("") +
      opt.felder.map((f) => '<option value="feld:' + esc(f) + '">Feld: ' + esc(f) + "</option>").join("");
    const haken = (name, text, an) => '<div class="form-check"><input class="form-check-input" type="checkbox" name="' + name +
      '" id="pl-' + name + '"' + (an ? " checked" : "") + '><label class="form-check-label" for="pl-' + name + '">' + text + "</label></div>";
    const dlg = document.createElement("dialog");
    dlg.className = "p-0 border-0 rounded shadow " + MARKE + "-export";
    dlg.innerHTML =
      '<form method="dialog" class="card" style="width:min(620px,94vw)">' +
      // Ohne diesen ersten, gesperrten Knopf schlösse „Enter" im Dateinamen den Dialog.
      '<button type="submit" disabled hidden aria-hidden="true"></button>' +
      '<div class="card-header">Export (' + ids.length + " Dokument" + (ids.length > 1 ? "e" : "") + ")</div>" +
      '<div class="card-body">' +
      '<div class="btn-group w-100 mb-3" role="group" aria-label="Exportart">' +
      '<input type="radio" class="btn-check" name="art" id="pl-art-ein" value="ein" checked>' +
      '<label class="btn btn-sm btn-outline-primary" for="pl-art-ein">Ein PDF</label>' +
      '<input type="radio" class="btn-check" name="art" id="pl-art-einzeln" value="einzeln">' +
      '<label class="btn btn-sm btn-outline-primary" for="pl-art-einzeln">Einzeln</label></div>' +
      '<div data-teil="ein"><div class="form-text mt-0 mb-2">Alle Dokumente zu einem PDF zusammengefügt, mit einem Lesezeichen je Dokument.</div>' +
      haken("seitenzahlen", "Seitenzahlen", true) +
      haken("inhalt", "Inhaltsverzeichnis vorne — Sprung zur Seite und Link nach Paperless", true) + "</div>" +
      '<div data-teil="einzeln" hidden><div class="form-text mt-0 mb-2">Jedes Dokument als eigene PDF-Datei, unverändert aus Paperless.</div>' +
      '<label class="form-label small mb-0" for="pl-vorlage">Dateiname</label>' +
      '<div class="input-group input-group-sm"><input class="form-control" name="vorlage" id="pl-vorlage" value="' + esc(opt.vorlage) +
      '" maxlength="300"><span class="input-group-text">.pdf</span></div>' +
      '<div class="mt-1 small" style="max-height:6.5em;overflow:auto">' + variablen + "</div>" +
      haken("nummerieren", "Durchnummerieren (001_, 002_, …)", false) +
      haken("zip", "Als ZIP herunterladen", true) +
      haken("verzeichnis", "Inhaltsverzeichnis-PDF dazu — Links auf die Dateien und nach Paperless", true) + "</div>" +
      '<label class="form-label small mb-0 mt-3" for="pl-sortierung">Sortierung</label>' +
      '<div class="input-group input-group-sm"><select class="form-select" name="sortierung" id="pl-sortierung">' + sortierung + "</select>" +
      '<select class="form-select" name="richtung" style="max-width:11em" aria-label="Richtung"><option value="auf">aufsteigend</option>' +
      '<option value="ab">absteigend</option></select></div>' +
      '<div class="form-text">Archiv-PDF aus Paperless, sonst das Original, wenn es ein PDF ist — andere werden übersprungen und gemeldet. ' +
      "Höchstens " + opt.grenzen.dokumente + " Dokumente und " + opt.grenzen.mb + " MB je Export.</div>" +
      '<div data-teil="stand" class="mt-3" hidden><div class="progress" style="height:6px"><div class="progress-bar" style="width:0%"></div></div>' +
      '<div class="small mt-2" data-text></div><div class="small mt-2" data-ergebnis></div></div>' +
      "</div>" +
      '<div class="card-footer d-flex gap-2 justify-content-end">' +
      '<button type="button" class="btn btn-sm btn-outline-secondary" data-zu>Schließen</button>' +
      '<button type="button" class="btn btn-sm btn-primary" data-los>Exportieren</button></div></form>';
    document.body.appendChild(dlg);
    const f = dlg.querySelector("form");
    const feld = (n) => f.querySelector('[name="' + n + '"]');
    const teil = (n) => dlg.querySelector('[data-teil="' + n + '"]');
    const art = () => f.querySelector('[name="art"]:checked').value;
    f.querySelectorAll('[name="art"]').forEach((r) => r.addEventListener("change", () => {
      teil("ein").hidden = art() !== "ein";
      teil("einzeln").hidden = art() !== "einzeln";
    }));
    dlg.querySelectorAll("[data-var]").forEach((b) => b.addEventListener("click", () => {
      const v = feld("vorlage"), a = v.selectionStart == null ? v.value.length : v.selectionStart;
      v.value = v.value.slice(0, a) + b.dataset.var + v.value.slice(v.selectionEnd == null ? a : v.selectionEnd);
      v.focus();
      v.selectionStart = v.selectionEnd = a + b.dataset.var.length;
    }));
    dlg.addEventListener("close", () => dlg.remove());
    const los = dlg.querySelector("[data-los]");
    const balken = dlg.querySelector(".progress-bar");
    const text = (t, fehler) => {
      const el = dlg.querySelector("[data-text]");
      el.className = "small mt-2" + (fehler ? " text-danger" : "");
      el.textContent = t;
    };
    // Ein Zustand für Knopf, Balken und Formular: „bereit" | „vorbereiten" | „laden" | „fertig".
    // Solange vorbereitet oder heruntergeladen wird, ist der Knopf gesperrt und sagt, was läuft.
    let zustand = "bereit";
    const laeuft = () => zustand === "vorbereiten" || zustand === "laden";
    const setzen = (z, prozent) => {
      zustand = z;
      los.disabled = laeuft();
      los.setAttribute("aria-busy", laeuft() ? "true" : "false");
      const spinner = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>';
      los.innerHTML = z === "vorbereiten" ? spinner + "Wird vorbereitet …"
        : z === "laden" ? spinner + "Wird heruntergeladen …"
        : z === "fertig" ? "Neu exportieren" : "Exportieren";
      f.querySelectorAll("input, select").forEach((el) => { el.disabled = laeuft(); });
      if (typeof prozent === "number") balken.style.width = prozent + "%";
      balken.classList.toggle("bg-success", z === "laden" || z === "fertig");
      balken.classList.toggle("progress-bar-striped", laeuft());
      balken.classList.toggle("progress-bar-animated", laeuft());
    };
    const schliessen = () => {
      if (laeuft() && !confirm("Der Export läuft noch. Dialog trotzdem schließen? " +
                               "Die Dateien werden dann nicht heruntergeladen.")) return;
      dlg.close();
    };
    dlg.querySelector("[data-zu]").addEventListener("click", schliessen);
    dlg.addEventListener("cancel", (ev) => { ev.preventDefault(); schliessen(); });   // Esc

    // Eine Datei laden, mit Stand in Text, Balken und (beim Klick) im Link selbst. Nie zwei
    // Downloads gleichzeitig — weder automatisch noch per Klick.
    let ladeSperre = false;
    const dateiLaden = async (job, st, nr, knopf) => {
      if (ladeSperre) return false;
      ladeSperre = true;
      const d = st.dateien[nr], vorher = knopf ? knopf.innerHTML : "";
      if (knopf) knopf.disabled = true;
      const zeigen = (p, da) => {
        const stand = p === null ? groesse(da) : p + " %";
        text(`Wird heruntergeladen: ${d.name} (Datei ${nr + 1} von ${st.dateien.length}) — ${stand}`);
        if (knopf) knopf.textContent = d.name + " — " + stand;
        if (p !== null) balken.style.width = Math.round((100 * nr + p) / st.dateien.length) + "%";
      };
      try {
        zeigen(0, 0);
        await herunterladen(job, nr, d.name, zeigen);
        return true;
      } catch (e) {
        text("paperlaiss: Herunterladen fehlgeschlagen — " + e.message, true);
        return false;
      } finally {
        ladeSperre = false;
        if (knopf) { knopf.disabled = false; knopf.innerHTML = vorher; }
      }
    };

    los.addEventListener("click", async () => {
      if (laeuft()) return;                                   // Reklick während des Laufs
      const daten = {
        docs: ids, art: art(), seitenzahlen: feld("seitenzahlen").checked,
        inhalt: art() === "ein" ? feld("inhalt").checked : feld("verzeichnis").checked,
        zip: feld("zip").checked, vorlage: feld("vorlage").value, nummerieren: feld("nummerieren").checked,
        sortierung: feld("sortierung").value, absteigend: feld("richtung").value === "ab", basis: paperlessBasis(),
      };
      setzen("vorbereiten", 0);
      teil("stand").hidden = false;
      dlg.querySelector("[data-ergebnis]").innerHTML = "";
      text("Export wird vorbereitet …");
      let job;
      try { job = (await panel("/knopf/export", daten)).job; }
      catch (e) { text("paperlaiss: " + e.message, true); setzen("bereit", 0); return; }
      let st = null;
      for (let i = 0; i < 1200 && dlg.isConnected; i++) {
        await new Promise((ok) => setTimeout(ok, 1500));
        try { st = await panel("/knopf/export/" + encodeURIComponent(job)); }
        catch (e) {
          text("paperlaiss: " + e.message, true);
          if (/^40[134] /.test(e.message)) break;          // abgelaufen, keine Sitzung, kein Recht
          continue;
        }
        balken.style.width = Math.round(100 * (st.status === "fertig" ? 1 : st.fertig / Math.max(1, st.gesamt))) + "%";
        text(st.status === "fehler" ? st.meldung
          : st.status === "fertig" ? "Vorbereitet." : "Wird vorbereitet: " + st.schritt + " …", st.status === "fehler");
        if (st.status === "fertig" || st.status === "fehler") break;
      }
      if (!dlg.isConnected) return;
      if (!st || !["fertig", "fehler"].includes(st.status)) { setzen("bereit"); return; }
      const erg = dlg.querySelector("[data-ergebnis]");
      let h = "";
      if (st.dateien.length) {
        h += '<div class="mb-1">Dateien (' + st.aufbewahrung_min + " Minuten lang erneut abrufbar):</div>" +
          st.dateien.map((d, nr) => '<div><button type="button" class="btn btn-link btn-sm p-0" data-nr="' + nr + '">' +
            esc(d.name) + "</button> · " + groesse(d.groesse) + "</div>").join("");
      }
      if (st.uebersprungen.length) {
        h += '<div class="mt-2 text-warning-emphasis">Nicht enthalten (' + st.uebersprungen.length + "):</div>" +
          st.uebersprungen.map((u) => "<div>#" + esc(u.id) + " " + esc(u.titel) + " — " + esc(u.grund) + "</div>").join("");
      }
      erg.innerHTML = h;
      if (st.status === "fehler") { setzen("bereit"); return; }
      erg.querySelectorAll("[data-nr]").forEach((b) => b.addEventListener("click", async () => {
        if (laeuft()) return;
        setzen("laden");
        if (await dateiLaden(job, st, +b.dataset.nr, b)) text("Heruntergeladen: " + st.dateien[+b.dataset.nr].name);
        setzen("fertig", 100);
      }));
      // Sofort herunterladen, eine Datei nach der anderen (bei mehreren fragt der Browser einmal nach).
      setzen("laden", 0);
      let ok = 0;
      for (let nr = 0; nr < st.dateien.length && dlg.isConnected; nr++) {
        if (!(await dateiLaden(job, st, nr, null))) break;
        ok++;
        await new Promise((weiter) => setTimeout(weiter, 400));
      }
      if (!dlg.isConnected) return;
      setzen("fertig", 100);
      if (ok === st.dateien.length) {
        text(`Fertig: ${ok} Datei${ok !== 1 ? "en" : ""} heruntergeladen` +
             (st.uebersprungen.length ? `, ${st.uebersprungen.length} Dokument(e) nicht enthalten.` : "."));
      }
    });
    dlg.showModal();
  }

  // ---------- Korrespondenten-Dialog: Abschnitt „paperlaiss" ----------
  // Paperless kann Korrespondenten keine eigenen Felder geben. paperlaiss führt dafür ein kleines
  // Adressbuch (Kontext für die KI, Aliase, Mail-Domains …) und blendet es hier ein. Die ID steht
  // im Dialogkopf („ID: 13"); ein neuer Korrespondent hat noch keine.
  async function einfuegenKorr() {
    const dlg = document.querySelector("pngx-correspondent-edit-dialog");
    const body = dlg && dlg.querySelector(".modal-body");
    if (!body || body.querySelector("." + MARKE)) return;
    const box = document.createElement("div");
    box.className = "mt-3 border-top pt-3 " + MARKE;
    body.appendChild(box);
    // Paperless setzt das Objekt (und damit die ID-Plakette) erst kurz nach dem Öffnen — ohne
    // Warten hielte der Abschnitt jeden Korrespondenten für neu.
    let m = null;
    for (let i = 0; i < 15 && !m; i++) {
      m = ((dlg.querySelector(".modal-header .badge") || {}).textContent || "").match(/(\d+)/);
      if (!m) await new Promise((ok) => setTimeout(ok, 200));
    }
    if (!m) {
      box.innerHTML = '<div class="small text-muted">paperlaiss: Stammdaten für die KI lassen sich eintragen, sobald der Korrespondent angelegt ist.</div>';
      return;
    }
    const cid = parseInt(m[1], 10);
    let d;
    try { d = await panel("/knopf/korrespondent/" + cid); }
    catch (e) { box.innerHTML = '<div class="small text-danger">paperlaiss: ' + esc(e.message) + "</div>"; return; }
    const aus = d.darf_aendern ? "" : " disabled";
    // Listenfelder (Telefon, Mail, IBAN …): oben die Werte als Text mit Stift und Mülleimer, darunter
    // ein Eingabefeld mit „+“ für einen neuen Wert (PO 2026-09-27). Der Stift macht aus der Zeile ein
    // Eingabefeld mit Haken; leer bestätigt heisst löschen.
    const knopfKlein = (attr, icon, titel) => '<button type="button" class="btn btn-sm btn-link text-secondary p-1" ' +
      attr + ' title="' + titel + '" aria-label="' + titel + '">' + icon + "</button>";
    // Herkunft je Wert (von der KI aus einem Dokument nachgetragen) — damit man es prüfen kann.
    const herkunft = (name, wert) => { const e = (d.werte.erfasst || {})[name]; return e && typeof e === "object" ? e[wert] || "" : ""; };
    const wertZeile = (wert, name) => '<div class="d-flex align-items-center border-bottom py-1" data-pl-wert="' + esc(wert) + '">' +
      '<span class="flex-grow-1 small text-break">' + esc(wert) +
      (name && herkunft(name, wert) ? ' <span class="text-muted">· ' + esc(herkunft(name, wert)) + "</span>" : "") + "</span>" +
      (aus ? "" : knopfKlein("data-pl-bearb", ICON.stift, "Bearbeiten") + knopfKlein("data-pl-weg", ICON.muell, "Löschen")) + "</div>";
    const feld = (name, art) => {
      const w = d.werte[name];
      if (art === "liste") {
        const liste = (Array.isArray(w) ? w : String(w || "").split(/[,;\n]/)).map((x) => String(x).trim()).filter(Boolean);
        return '<div data-pl-feld="' + name + '">' + [...new Set(liste)].map((x) => wertZeile(x, name)).join("") + "</div>" +
          (aus ? (liste.length ? "" : '<div class="small text-muted">—</div>')
               : '<div class="input-group input-group-sm mt-1"><input class="form-control" data-pl-neu="' + name +
                 '" placeholder="Hinzufügen …">' + '<button type="button" class="btn btn-outline-primary" data-pl-plus="' + name +
                 '" title="Hinzufügen" aria-label="Hinzufügen">' + ICON.plus + "</button></div>");
      }
      return art === "lang" ? '<textarea class="form-control form-control-sm" rows="2" data-pl="' + name + '"' + aus + ">" + esc(w) + "</textarea>"
                            : '<input class="form-control form-control-sm" data-pl="' + name + '" value="' + esc(w) + '"' + aus + ">";
    };
    box.innerHTML = '<h6 class="mb-1">paperlaiss — Stammdaten für die KI</h6>' +
      '<div class="small text-muted mb-2">Hilft beim Zuordnen: Kontext und Kennungen gehen in den Prompt, Aliase und Domains in den Abgleich. Telefonnummern ohne Leerzeichen, mit Landesvorwahl (+43…) oder national (0…) — gefunden wird beides. Gespeichert mit „Save".</div>' +
      d.felder.map(([name, titel, art]) => '<div class="mb-2"><label class="form-label small mb-0">' + esc(titel) +
        // Von der KI aus einem Dokument nachgetragen: sagen, woher — damit man es prüfen kann.
        (typeof (d.werte.erfasst || {})[name] === "string" ? ' <span class="text-muted">· erfasst: ' + esc(d.werte.erfasst[name]) + "</span>" : "") + "</label>" +
        feld(name, art) + "</div>").join("");
    if (!d.darf_aendern) return;
    const liste = (name) => box.querySelector('[data-pl-feld="' + name + '"]');
    const vorhanden = (name, wert, ausser) => [...liste(name).querySelectorAll("[data-pl-wert]")]
      .some((z) => z !== ausser && z.dataset.plWert === wert);
    const hinzu = (name) => {
      const eing = box.querySelector('[data-pl-neu="' + name + '"]');
      const wert = eing.value.trim();
      if (wert && !vorhanden(name, wert)) liste(name).insertAdjacentHTML("beforeend", wertZeile(wert));
      eing.value = "";
      eing.focus();
    };
    const bearbeiten = (z) => {
      z.dataset.plAlt = z.dataset.plWert;
      z.innerHTML = '<div class="input-group input-group-sm"><input class="form-control" data-pl-edit value="' + esc(z.dataset.plWert) + '">' +
        '<button type="button" class="btn btn-outline-primary" data-pl-ok title="Übernehmen" aria-label="Übernehmen">' + ICON.haken + "</button></div>";
      z.querySelector("input").focus();
    };
    const uebernehmen = (z, abbrechen) => {
      const name = z.parentElement.dataset.plFeld;
      const wert = abbrechen ? z.dataset.plAlt : z.querySelector("[data-pl-edit]").value.trim();
      if (!wert || vorhanden(name, wert, z)) { z.remove(); return; }
      z.outerHTML = wertZeile(wert);
    };
    box.addEventListener("click", (ev) => {
      const t = ev.target.closest("[data-pl-plus], [data-pl-weg], [data-pl-bearb], [data-pl-ok]");
      if (!t) return;
      const z = t.closest("[data-pl-wert]");
      if (t.dataset.plPlus) hinzu(t.dataset.plPlus);
      else if (t.hasAttribute("data-pl-weg")) z.remove();
      else if (t.hasAttribute("data-pl-bearb")) bearbeiten(z);
      else uebernehmen(z, false);
    });
    // Enter im Feld fügt hinzu bzw. übernimmt — und darf nicht Paperless' Formular absenden.
    box.addEventListener("keydown", (ev) => {
      const neu = ev.target.closest("[data-pl-neu]"), edit = ev.target.closest("[data-pl-edit]");
      if (!neu && !edit) return;
      if (ev.key === "Enter") {
        ev.preventDefault();
        if (neu) hinzu(neu.dataset.plNeu); else uebernehmen(edit.closest("[data-pl-wert]"), false);
      } else if (ev.key === "Escape" && edit) {
        ev.preventDefault(); ev.stopPropagation();
        uebernehmen(edit.closest("[data-pl-wert]"), true);
      }
    });
    const form = dlg.querySelector("form");
    // Fangphase: vor Paperless' eigenem Speichern, das den Dialog danach schliesst.
    form.addEventListener("submit", () => {
      const daten = {};
      box.querySelectorAll("[data-pl]").forEach((el) => { daten[el.dataset.pl] = el.value; });
      // Je Listenfeld: die Werte, dazu ein offenes Bearbeiten und was im Eingabefeld steht, aber noch
      // nicht mit „+“ bestätigt ist — „Save“ soll nichts verwerfen, was sichtbar eingetippt wurde.
      box.querySelectorAll("[data-pl-feld]").forEach((l) => {
        daten[l.dataset.plFeld] = [...l.querySelectorAll("[data-pl-wert]")].map((z) => {
          const e = z.querySelector("[data-pl-edit]");
          return e ? e.value : z.dataset.plWert;
        });
        const neu = box.querySelector('[data-pl-neu="' + l.dataset.plFeld + '"]');
        if (neu && neu.value.trim()) daten[l.dataset.plFeld].push(neu.value);
      });
      panel("/knopf/korrespondent/" + cid, daten)
        .then(() => meldung("paperlaiss: Stammdaten gespeichert.", "success"))
        .catch((e) => meldung("paperlaiss: Stammdaten NICHT gespeichert — " + e.message, "danger"));
    }, true);
  }

  // ---------- Profil-Menü oben rechts: Link zum paperlaiss-Panel (neuer Tab), nur für Superuser ----------
  // Das Panel lässt ohnehin nur die Admin-Gruppe hinein — anderen Nutzern zeigte der Link nur eine Absage.
  let superuser = null;
  async function einfuegenProfil() {
    const menu = document.querySelector('[aria-labelledby="userDropdown"]');
    if (!menu || menu.querySelector("." + MARKE)) return;
    const einstellungen = [...menu.querySelectorAll("a")].find((a) => /(^|\/)settings$/.test(a.getAttribute("href") || ""));
    if (!einstellungen) return;
    if (superuser === null) {
      superuser = false;
      try {
        const r = await fetch(new URL("api/ui_settings/", document.baseURI), { credentials: "include", headers: { Accept: "application/json" } });
        superuser = r.ok && !!((await r.json()).user || {}).is_superuser;
      } catch (e) { /* kein Link */ }
    }
    if (!superuser || menu.querySelector("." + MARKE)) return;
    const a = document.createElement("a");
    a.className = einstellungen.className + " " + MARKE;
    a.href = PANEL + "/";
    a.target = "_blank";
    a.rel = "noopener";
    a.innerHTML = '<span class="me-2">' + ICON.panel + "</span>paperlaiss-Panel";
    einstellungen.parentNode.insertBefore(a, einstellungen);
  }

  function alles() { einfuegenDetail(); einfuegenListe(); einfuegenKorr(); einfuegenProfil(); }
  new MutationObserver(alles).observe(document.documentElement, { childList: true, subtree: true });
  alles();
})();
