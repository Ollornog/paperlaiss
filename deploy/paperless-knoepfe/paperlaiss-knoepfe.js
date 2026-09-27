/*
 * paperlaiss — zwei Knöpfe in der Dokumentansicht von Paperless-ngx.
 *
 *   KI  (Zauberstab)  optionaler Hinweis, dann neu klassifizieren (immer mit Mistral-OCR)
 *   OCR (Textblatt)   nur den Text per Mistral-OCR neu lesen, Metadaten bleiben
 *
 * In der Dokumentansicht ersetzen sie Paperless' eigenes „Suggest" (ausgeblendet); in der
 * Dokumentliste stehen sie in der Leiste der Mehrfachauswahl und gelten für alle markierten.
 *
 * Kein Fork: Paperless lädt diese Datei, weil ein Init-Skript sie beim Start einhängt
 * (10-paperlaiss-knoepfe.sh). Die Knöpfe sprechen NUR die Paperless-API mit der Sitzung des
 * Nutzers an — sie setzen Tag bzw. Hinweisfeld, den Rest erledigt der Paperless-Workflow mit
 * dem Webhook auf paperlaiss. Wer das Dokument nicht bearbeiten darf, bekommt eine 403.
 *
 * Ändert Paperless den Aufbau der Seite, fehlen die Knöpfe — Paperless selbst bleibt heil.
 * Icons: Bootstrap Icons „magic" und „file-earmark-text" (MIT, The Bootstrap Authors).
 */
(function () {
  "use strict";
  // Vom Init-Skript ersetzt (Umgebungsvariablen PAPERLAISS_REDO_TAG / _OCR_TAG / _HINWEIS_FELD).
  const NAMEN = { tag: "%%REDO_TAG%%", ocrTag: "%%OCR_TAG%%", feld: "%%HINWEIS_FELD%%" };
  const MARKE = "paperlaiss-knoepfe";
  const ICON = {
    ki: '<svg width="1.2em" height="1.2em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M9.5 2.672a.5.5 0 1 0 1 0V.843a.5.5 0 0 0-1 0zm4.5.035A.5.5 0 0 0 13.293 2L12 3.293a.5.5 0 1 0 .707.707zM7.293 4A.5.5 0 1 0 8 3.293L6.707 2A.5.5 0 0 0 6 2.707zm-.621 2.5a.5.5 0 1 0 0-1H4.843a.5.5 0 1 0 0 1zm8.485 0a.5.5 0 1 0 0-1h-1.829a.5.5 0 0 0 0 1zM13.293 10A.5.5 0 1 0 14 9.293L12.707 8a.5.5 0 1 0-.707.707zM9.5 11.157a.5.5 0 0 0 1 0V9.328a.5.5 0 0 0-1 0zm1.854-5.097a.5.5 0 0 0 0-.706l-.708-.708a.5.5 0 0 0-.707 0L8.646 5.94a.5.5 0 0 0 0 .707l.708.708a.5.5 0 0 0 .707 0l1.293-1.293Zm-3 3a.5.5 0 0 0 0-.706l-.708-.708a.5.5 0 0 0-.707 0L.646 13.94a.5.5 0 0 0 0 .707l.708.708a.5.5 0 0 0 .707 0z"/></svg>',
    ocr: '<svg width="1.2em" height="1.2em" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M5.5 7a.5.5 0 0 0 0 1h5a.5.5 0 0 0 0-1zM5 9.5a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5a.5.5 0 0 1-.5-.5m0 2a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 0 1h-2a.5.5 0 0 1-.5-.5"/><path d="M9.5 0H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4.5zm0 1v2A1.5 1.5 0 0 0 11 4.5h2V14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1z"/></svg>',
  };

  function dokId() {
    const m = location.pathname.match(/\/documents\/(\d+)(\/|$)/);
    return m ? parseInt(m[1], 10) : null;
  }

  function csrf() {
    const m = document.cookie.split("; ").find((c) => /csrftoken=/.test(c));
    return m ? decodeURIComponent(m.split("=").slice(1).join("=")) : "";
  }

  async function api(pfad, daten, methode) {
    const r = await fetch("/api" + pfad, {
      method: methode || "GET",
      credentials: "same-origin",
      headers: Object.assign({ Accept: "application/json" },
        daten ? { "Content-Type": "application/json", "X-CSRFToken": csrf() } : {}),
      body: daten ? JSON.stringify(daten) : undefined,
    });
    if (!r.ok) throw new Error(r.status + " " + (await r.text()).slice(0, 200));
    return r.json();
  }

  async function idVon(art, name) {
    if (!name) return null;
    const d = await api(`/${art}/?name__iexact=${encodeURIComponent(name)}`);
    return d.results && d.results.length ? d.results[0].id : null;
  }

  function meldung(text, art) {
    let el = document.getElementById(MARKE + "-meldung");
    if (!el) {
      el = document.createElement("div");
      el.id = MARKE + "-meldung";
      el.setAttribute("role", "status");
      el.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2000;max-width:360px";
      document.body.appendChild(el);
    }
    el.className = "alert shadow-sm mb-0 alert-" + (art || "info");
    el.textContent = text;
    if (art === "success") setTimeout(() => el.remove(), 4000);
  }

  // Wartet, bis paperlaiss fertig ist. paperlaiss räumt vor dem Lauf den Auslöser weg — beim
  // Neu-Klassifizieren auch den Marker-Tag, den es am Ende wieder setzt. Also: erst merken,
  // welche Tags verschwunden sind; fertig, wenn alle außer dem Auslöser zurück sind. Beim
  // reinen OCR entfernt paperlaiss den OCR-Tag erst zusammen mit dem Text: weg = fertig.
  // Danach neu laden — sonst speichert Paperless beim nächsten „Speichern" seinen alten Stand.
  async function warten(id, vorher, ausloeserId, nurOcr) {
    let weg = null, stand = null;
    for (let i = 0; i < 90; i++) {
      await new Promise((ok) => setTimeout(ok, 3000));
      let d;
      try { d = await api(`/documents/${id}/`); } catch (e) { continue; }
      const tags = d.tags || [];
      if (weg === null) {
        if (tags.includes(ausloeserId)) continue;
        weg = nurOcr ? [] : vorher.filter((t) => t !== ausloeserId && !tags.includes(t));
        stand = d.modified;
        if (weg.length) continue;
      }
      const fertig = nurOcr || (weg.length ? weg.every((t) => tags.includes(t)) : d.modified !== stand);
      if (fertig) {
        meldung("paperlaiss ist fertig — lade neu …", "success");
        setTimeout(() => location.reload(), 800);
        return;
      }
    }
    meldung("paperlaiss antwortet nicht (Zeitüberschreitung). Panel und Protokoll prüfen.", "warning");
  }

  async function ausloesen(modus, hinweis) {
    const id = dokId();
    if (!id) return;
    try {
      const tagName = modus === "ocr" ? NAMEN.ocrTag : NAMEN.tag;
      const tagId = await idVon("tags", tagName);
      if (!tagId) throw new Error(`Tag „${tagName}" fehlt in Paperless — deploy/neu-klassifizieren-einrichten.py ausführen`);
      const d = await api(`/documents/${id}/`);
      const patch = { tags: Array.from(new Set([...(d.tags || []), tagId])) };
      if (hinweis) {
        const fid = await idVon("custom_fields", NAMEN.feld);
        if (!fid) throw new Error(`Feld „${NAMEN.feld}" fehlt in Paperless`);
        patch.custom_fields = (d.custom_fields || []).filter((c) => c.field !== fid)
          .map((c) => ({ field: c.field, value: c.value })).concat([{ field: fid, value: hinweis }]);
      }
      await api(`/documents/${id}/`, patch, "PATCH");
      meldung(modus === "ocr" ? "paperlaiss liest den Text neu …" : "paperlaiss klassifiziert neu (mit OCR) …");
      warten(id, d.tags || [], tagId, modus === "ocr");
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

  function knopf(icon, text, titel, aktion) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-sm btn-outline-primary";
    b.title = titel;
    b.innerHTML = icon + '<span class="d-none d-lg-inline ps-1">' + text + "</span>";
    b.addEventListener("click", aktion);
    return b;
  }

  function einfuegen() {
    if (!dokId() || document.querySelector("." + MARKE)) return;
    const zauberstab = document.querySelector("pngx-suggestions-dropdown");
    const gruppe = zauberstab && zauberstab.closest(".btn-group");
    if (!gruppe) return;
    const g = document.createElement("div");
    g.className = "btn-group " + MARKE;
    g.appendChild(knopf(ICON.ki, "KI", "paperlaiss: neu klassifizieren (optional mit Hinweis)",
      () => dialogKi(1, (h) => ausloesen("ki", h))));
    g.appendChild(knopf(ICON.ocr, "OCR", "paperlaiss: Text per OCR neu lesen", () => {
      if (confirm("Text dieses Dokuments per Mistral-OCR neu lesen? Die Metadaten bleiben.")) ausloesen("ocr");
    }));
    gruppe.after(g);
    gruppe.style.display = "none";   // Paperless' eigenes „Suggest" — paperlaiss ersetzt es
  }

  // ---------- Mehrfachauswahl in der Dokumentliste ----------
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

  async function mehrfach(modus, hinweis) {
    const ids = auswahl();
    if (!ids.length) { meldung("paperlaiss: keine sichtbaren Dokumente markiert.", "warning"); return; }
    try {
      let aufruf;
      if (modus === "ki" && hinweis) {
        // NUR das Feld setzen: ein befülltes Hinweisfeld löst allein aus. Tag UND Feld wären zwei
        // Sammelaufrufe, also zwei Workflow-Läufe je Dokument.
        const fid = await idVon("custom_fields", NAMEN.feld);
        if (!fid) throw new Error(`Feld „${NAMEN.feld}" fehlt in Paperless`);
        aufruf = { method: "modify_custom_fields",
                   parameters: { add_custom_fields: { [fid]: hinweis }, remove_custom_fields: [] } };
      } else {
        const name = modus === "ocr" ? NAMEN.ocrTag : NAMEN.tag;
        const tid = await idVon("tags", name);
        if (!tid) throw new Error(`Tag „${name}" fehlt in Paperless`);
        aufruf = { method: "add_tag", parameters: { tag: tid } };
      }
      await api("/documents/bulk_edit/", Object.assign({ documents: ids }, aufruf), "POST");
      meldung(`paperlaiss: ${ids.length} Dokument(e) übergeben — ` +
              (modus === "ocr" ? "Text wird neu gelesen." : "werden neu klassifiziert (mit OCR).") +
              " Die Liste zeigt das Ergebnis nach dem Neuladen.", "success");
    } catch (e) {
      meldung("paperlaiss: " + e.message, "danger");
    }
  }

  function mehrfachPruefen(weiter) {
    const ids = auswahl(), gesamt = markiertLautPaperless();
    if (gesamt !== null && gesamt > ids.length &&
        !confirm(`Markiert sind ${gesamt}, sichtbar sind ${ids.length}. paperlaiss verarbeitet nur die ` +
                 `${ids.length} sichtbaren. Fortfahren?`)) return;
    weiter(ids.length);
  }

  function einfuegenListe() {
    // Direkter Pfad: ein blosses ".ms-auto" trifft zuerst die Zaehl-Plaketten in den Dropdowns.
    const leiste = document.querySelector("pngx-bulk-editor > div > div.ms-auto");
    if (!leiste || leiste.querySelector("." + MARKE)) return;
    const g = document.createElement("div");
    g.className = "btn-group " + MARKE;
    g.appendChild(knopf(ICON.ki, "KI", "paperlaiss: markierte neu klassifizieren (optional mit Hinweis)",
      () => mehrfachPruefen((n) => dialogKi(n, (h) => mehrfach("ki", h)))));
    g.appendChild(knopf(ICON.ocr, "OCR", "paperlaiss: Text der markierten per OCR neu lesen",
      () => mehrfachPruefen((n) => {
        if (confirm(`Text von ${n} Dokument(en) per Mistral-OCR neu lesen? Die Metadaten bleiben.`)) mehrfach("ocr");
      })));
    leiste.prepend(g);
  }

  function alles() { einfuegen(); einfuegenListe(); }
  new MutationObserver(alles).observe(document.documentElement, { childList: true, subtree: true });
  alles();
})();
