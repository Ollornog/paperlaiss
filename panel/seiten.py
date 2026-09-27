"""Seiteninhalte des Panels — Aktivität, Ablauf & Prompt, Einstellungen.

Nur Inhalt: das Gerüst (Titelleiste, Navigation) kommt aus `huelle.py`, das Aussehen aus C22.
Die Seiten laden ihre Daten per JSON-API nach; die Entscheidungen (Filtern, Zählen, Blättern,
Typumwandlung) stehen getestet in `kern.py`, hier wird nur dargestellt.

Klassen im JavaScript stehen immer in doppelten Anführungszeichen (class=, dann "), damit
`tests/test_c22_klassen.py` sie gegen das C22-Pack prüfen kann.
"""
from __future__ import annotations

from huelle import abschnitt, dialog, kopf, symbol

# Die fünf Kennzahlen: Art (wie kern.log_art), Titel, Symbol, Badge-Variante.
ARTEN = [
    ("klassifiziert", "Klassifiziert", "circle-check", "success"),
    ("ocr", "OCR gelesen", "file-text", "info"),
    ("repariert", "Repariert", "refresh-ccw", "secondary"),
    ("fehler", "Fehler", "circle-alert", "destructive"),
    ("uebersprungen", "Übersprungen", "clock", "outline"),
]

# Gemeinsame Helfer für alle Seiten: Escapen, JSON holen/senden, einfaches Markdown.
_JS_GRUND = r"""
function txt(v){return String(v==null?'':v).replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]))}
async function holen(u,o){const r=await fetch(u,o);if(!r.ok)throw new Error(r.status+' '+(await r.text()).slice(0,200));return r.json()}
function senden(u,body){return holen(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}
// Markdown, wie ihn Mistral-OCR liefert: Überschriften, Tabellen, Listen, Fettdruck. Erst escapen,
// dann auszeichnen — der Text kommt aus einem fremden Dokument und darf kein HTML einschleusen.
function md(roh){
  const zeilen=txt(roh||'').split('\n'); let h='', tab=[], liste=[];
  const inline=s=>s.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>');
  const tabZu=()=>{ if(!tab.length) return; const z=tab.filter(t=>!/^\s*\|?\s*:?-{2,}/.test(t));
    h+='<div class="overflow-x-auto"><table class="table"><tbody>'+z.map(t=>'<tr>'+t.replace(/^\s*\||\|\s*$/g,'').split('|')
      .map(c=>'<td>'+inline(c.trim())+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'; tab=[]; };
  const listeZu=()=>{ if(!liste.length) return; h+='<ul class="space-y-1">'+liste.map(l=>'<li>• '+inline(l)+'</li>').join('')+'</ul>'; liste=[]; };
  for(const z of zeilen){
    if(/^\s*\|/.test(z)){ listeZu(); tab.push(z); continue; } tabZu();
    const m=z.match(/^\s*[-*]\s+(.*)/); if(m){ liste.push(m[1]); continue; } listeZu();
    const u=z.match(/^(#{1,6})\s+(.*)/);
    if(u) h+='<p class="mt-3 font-semibold">'+inline(u[2])+'</p>';
    else if(z.trim()) h+='<p>'+inline(z)+'</p>';
  }
  tabZu(); listeZu(); return h;
}
"""


# ---------------------------------------------------------------- Aktivität
def aktivitaet() -> str:
    karten = "".join(
        f'<button type="button" class="card min-w-48 flex-1 cursor-pointer text-left hover:border-ring" data-size="sm" '
        f'data-art="{art}" onclick="setzeFilter({{art:\'{art}\'}})">'
        f'<header><h2 class="flex items-center gap-2">{symbol(sym, "size-4")}{titel}</h2></header>'
        f'<section><span class="text-2xl font-semibold tabular-nums" id="kz-{art}">…</span></section></button>'
        for art, titel, sym, _ in ARTEN)
    manuell = (
        '<form class="flex items-center gap-2" onsubmit="event.preventDefault();anstossen(this.doc.value,\'classify\')">'
        '<input class="input w-28" name="doc" inputmode="numeric" placeholder="Dok-ID" aria-label="Dokument-ID">'
        f'<button class="btn" data-size="sm" type="submit">{symbol("refresh-ccw")}Neu klassifizieren</button>'
        f'<button class="btn" data-variant="outline" data-size="sm" type="button" '
        f'onclick="anstossen(this.form.doc.value,\'ocr\')">{symbol("file-text")}mit OCR</button></form>')
    filterleiste = (
        '<div id="filter" class="mt-6 flex flex-wrap items-center gap-2" hidden>'
        '<span class="text-muted-foreground text-sm">Gefiltert:</span><span id="filter-text" class="badge" data-variant="secondary"></span>'
        f'<button type="button" class="btn" data-variant="outline" data-size="sm" onclick="history.back()">'
        f'{symbol("chevron-left")}Zurück</button>'
        f'<button type="button" class="btn" data-variant="ghost" data-size="sm" onclick="setzeFilter({{}})">'
        f'{symbol("funnel-x")}Filter aufheben</button></div>')
    tabelle = (
        '<div class="overflow-x-auto"><table class="table"><thead><tr>'
        '<th>Zeit</th><th>Dokument</th><th>Ereignis</th><th>Korrespondent</th><th>Typ</th><th>Hinweis</th>'
        '</tr></thead><tbody id="zeilen"><tr><td colspan="6" class="text-muted-foreground">lädt…</td></tr></tbody></table></div>'
        '<nav id="seiten" role="navigation" aria-label="Seitennavigation" data-pagination '
        'class="mt-4 flex w-full justify-center"></nav>')
    lauf = dialog("lauf", "Lauf", (
        '<div class="tabs w-full" id="lauf-tabs"><nav role="tablist" data-variant="line">'
        '<button type="button" role="tab" id="lt-1" aria-controls="lp-1" aria-selected="true" tabindex="0">Entscheidungsbaum</button>'
        '<button type="button" role="tab" id="lt-2" aria-controls="lp-2" aria-selected="false" tabindex="-1">Prompt</button>'
        '<button type="button" role="tab" id="lt-3" aria-controls="lp-3" aria-selected="false" tabindex="-1">Ausgabe</button>'
        '<button type="button" role="tab" id="lt-4" aria-controls="lp-4" aria-selected="false" tabindex="-1">Text</button></nav>'
        '<div role="tabpanel" id="lp-1" aria-labelledby="lt-1" tabindex="-1" class="pt-4"></div>'
        '<div role="tabpanel" id="lp-2" aria-labelledby="lt-2" tabindex="-1" class="pt-4" hidden></div>'
        '<div role="tabpanel" id="lp-3" aria-labelledby="lt-3" tabindex="-1" class="pt-4" hidden></div>'
        '<div role="tabpanel" id="lp-4" aria-labelledby="lt-4" tabindex="-1" class="pt-4" hidden></div></div>'))
    arten_js = "{" + ",".join(f"'{a}':['{t}','{v}']" for a, t, _, v in ARTEN) + ",'info':['Info','outline'],'vorschlag':['Vorschlag','outline']}"
    return (
        kopf("Aktivität", "Was der Klassifizierer getan hat. Kästen und Verlauf filtern, eine Zeile öffnet den Lauf.",
             manuell)
        + '<div id="laufend" class="mb-4"></div>'
        + f'<div class="flex flex-wrap gap-4">{karten}</div>'
        + abschnitt("Verlauf (30 Tage) — Klick auf einen Tag filtert", '<div id="verlauf" class="mx-auto w-full max-w-2xl"></div>')
        + filterleiste
        + abschnitt("Einträge", tabelle, '<span id="anzahl" class="text-muted-foreground text-sm"></span>')
        + lauf
        + "<script>" + _JS_GRUND + "const ARTEN=" + arten_js + ";" + _JS_AKTIVITAET + "</script>"
    )


_JS_AKTIVITAET = r"""
let F=Object.fromEntries(new URLSearchParams(location.search)); let TYPEN={};
function setzeFilter(neu, ersetzen){
  const f={...neu}; if(!('seite' in neu)) delete f.seite;
  const q=new URLSearchParams(Object.entries(f).filter(([k,v])=>v!=null&&v!=='')).toString();
  // Filter landen in der Adresse: „Zurück" im Browser und der Zurück-Knopf heben sie wieder auf.
  (ersetzen?history.replaceState:history.pushState).call(history,f,'',q?'?'+q:location.pathname);
  F=f; laden();
}
window.addEventListener('popstate',()=>{F=Object.fromEntries(new URLSearchParams(location.search));laden()});
function badge(art){const a=ARTEN[art]||[art,'outline'];return '<span class="badge" data-variant="'+a[1]+'">'+txt(a[0])+'</span>'}
async function laden(){
  const q=new URLSearchParams({...F}); let d;
  try{ d=await holen('/api/aktivitaet?'+q); }catch(e){ document.getElementById('zeilen').innerHTML='<tr><td colspan="6">'+txt(e.message)+'</td></tr>'; return; }
  TYPEN=d.typen||TYPEN;
  for(const [a,n] of Object.entries(d.kennzahlen)){const el=document.getElementById('kz-'+a); if(el) el.textContent=n;}
  document.querySelectorAll('[data-art]').forEach(k=>k.classList.toggle('border-primary',k.dataset.art===F.art));
  const teile=[]; if(F.art) teile.push((ARTEN[F.art]||[F.art])[0]); if(F.tag) teile.push(F.tag); if(F.doc) teile.push('Dokument '+F.doc);
  document.getElementById('filter').hidden=!teile.length; document.getElementById('filter-text').textContent=teile.join(' · ');
  document.getElementById('anzahl').textContent=d.gesamt+' Einträge';
  const tb=document.getElementById('zeilen');
  tb.innerHTML = d.eintraege.length ? d.eintraege.map(e=>{
    const typ = e.typ ? (TYPEN[e.typ]||e.typ) : '';
    const korr = e.korrespondent ? txt(e.korrespondent)+(e.korrespondent_neu?' <span class="badge" data-variant="warning">neu</span>':'') : '';
    const hinweis = e.ocr ? 'mit OCR' : (e.art==='fehler'||e.art==='info'||e.art==='ocr'||e.art==='uebersprungen' ? txt(e.text.replace(/^\S+\s+\d+:?\s*\|?\s*/,'')).slice(0,90) : '');
    return '<tr class="cursor-pointer hover:bg-muted" onclick="lauf('+(e.doc||0)+')">'+
      '<td class="whitespace-nowrap tabular-nums text-muted-foreground">'+txt(e.ts)+'</td>'+
      '<td class="tabular-nums">'+(e.doc?'#'+e.doc:'—')+'</td><td>'+badge(e.art)+'</td>'+
      '<td>'+korr+'</td><td>'+txt(typ)+'</td><td class="text-muted-foreground text-sm">'+hinweis+'</td></tr>';
  }).join('') : '<tr><td colspan="6" class="text-muted-foreground">Keine Einträge für diesen Filter.</td></tr>';
  seiten(d.seite,d.seiten);
}
function seiten(s,n){
  const nav=document.getElementById('seiten'); if(n<=1){nav.innerHTML='';return;}
  const knopf=(z,t,aktiv)=>'<li><a href="#" class="btn" data-variant="'+(aktiv?'outline':'ghost')+'" data-size="icon"'+(aktiv?' aria-current="page"':'')+
    ' onclick="event.preventDefault();setzeFilter({...F,seite:'+z+'})">'+t+'</a></li>';
  let h='<ul class="flex flex-row items-center gap-1">';
  if(s>1) h+='<li><a href="#" class="btn" data-variant="ghost" onclick="event.preventDefault();setzeFilter({...F,seite:'+(s-1)+'})">Zurück</a></li>';
  const zeig=new Set([1,n,s-1,s,s+1].filter(z=>z>=1&&z<=n)); let vorher=0;
  for(const z of [...zeig].sort((a,b)=>a-b)){ if(z-vorher>1) h+='<li><span class="btn text-muted-foreground" data-variant="ghost" data-size="icon" aria-hidden="true">…</span></li>'; h+=knopf(z,z,z===s); vorher=z; }
  if(s<n) h+='<li><a href="#" class="btn" data-variant="ghost" onclick="event.preventDefault();setzeFilter({...F,seite:'+(s+1)+'})">Weiter</a></li>';
  nav.innerHTML=h+'</ul>';
}
async function verlauf(){
  let d; try{ d=await holen('/api/verlauf?tage=30'); }catch(e){ return; }
  const tage=d.verlauf||[]; const el=document.getElementById('verlauf');
  const serien=[['klassifiziert','Klassifiziert'],['ocr','OCR'],['fehler','Fehler'],['uebersprungen','Übersprungen']];
  // Nur jeden fünften Tag beschriften — 30 Datumsangaben überlappen auf der Achse.
  el.dataset.chart=JSON.stringify({type:'stacked',legend:true,labels:tage.map((t,i)=>(i%5===0||i===tage.length-1)?t.tag.slice(8)+'.'+t.tag.slice(5,7)+'.':''),
    series:serien.map(([k,n])=>({name:n,data:tage.map(t=>t[k]||0)}))});
  delete el.dataset.c22ChartWired; if(window.C22&&C22.wireChart) C22.wireChart(el);
  // Klick auf einen Tag: C22 legt je Kategorie eine Trefferfläche rect[data-hit=i] über das Diagramm.
  el.onclick=ev=>{const h=ev.target.closest('[data-hit]'); if(h&&tage[+h.dataset.hit]) setzeFilter({...F,tag:tage[+h.dataset.hit].tag});};
}
async function laufend(){
  try{ const d=await holen('/api/running'); const el=document.getElementById('laufend');
    el.innerHTML=(d.jobs||[]).map(j=>'<span class="badge" data-variant="info">läuft: #'+txt(j.doc||j.id)+' · '+txt(j.stage||'')+' · '+j.dauer+' s</span>').join(' ');
  }catch(e){}
}
async function anstossen(doc,modus){
  doc=String(doc||'').trim(); if(!/^\d+$/.test(doc)) return;
  try{ await senden('/api/reclassify',{doc:doc,mode:modus}); }catch(e){ alert(e.message); }
  laden(); laufend();
}
// ---- Lauf-Dialog: Entscheidungsbaum, Prompt, Ausgabe, Text ----
function knoten(titel,ergebnis,variante,inhalt){
  return '<div class="card" data-size="sm"><header class="flex flex-wrap items-center justify-between gap-2"><h2>§ '+titel+'</h2>'+
    (ergebnis?'<span class="badge" data-variant="'+variante+'">'+txt(ergebnis)+'</span>':'')+'</header>'+
    (inhalt?'<section class="text-sm">'+inhalt+'</section>':'')+'</div>';
}
const PFEIL='<div class="flex justify-center text-muted-foreground">'+%PFEIL%+'</div>';
function code(v){return '<pre class="code-block max-h-96 overflow-auto"><code>'+txt(typeof v==='string'?v:JSON.stringify(v,null,2))+'</code></pre>'}
async function lauf(doc){
  if(!doc) return; const dlg=document.getElementById('lauf');
  document.getElementById('lauf-titel').textContent='Lauf · Dokument #'+doc;
  ['lp-1','lp-2','lp-3','lp-4'].forEach(i=>document.getElementById(i).innerHTML='<p class="text-muted-foreground">lädt…</p>');
  dlg.showModal();
  let t; try{ t=await holen('/api/trace/'+doc); }catch(e){ document.getElementById('lp-1').innerHTML='<p>Kein Ablauf gespeichert ('+txt(e.message)+'). Aufgezeichnet wird je Dokument der letzte Lauf.</p>'; return; }
  const o=t.ocr||{}, p0=t.pass0||{}, p1=t.pass1||{}, r=p1.response||{}, k=t.correspondent||{}, w=t.writeback||{};
  const b=[];
  b.push(knoten('Auslöser',t.trigger||'automatisch','secondary',(t.hinweis?'Hinweis: „'+txt(t.hinweis)+'"<br>':'')+'Zuletzt: '+txt(t.ts)));
  b.push(knoten('OCR vor der Analyse', o.triggered?(o.verworfen?'verworfen':o.error?'Fehler':'gelesen'):'nicht nötig',
    o.error?'destructive':o.triggered?'info':'success', txt(o.grund||'')+(o.chars?' · '+o.chars+' Zeichen':'')+(o.verworfen?' · '+txt(o.verworfen):'')+(o.error?' · '+txt(o.error):'')));
  if(t.pass0) b.push(knoten('Pass 0 — Absender', p0.vorschlag||'keiner','secondary','Kandidaten: '+(p0.kandidaten||[]).map(txt).join(', ')));
  b.push(knoten('Pass 1 — Analyse', r.document_type||'kein Typ', r.document_type?'success':'warning',
    'Korrespondent: '+txt(r.correspondent||'—')+' · Datum: '+txt(r.document_date||'—')+(r.needs_ocr?' · <span class="badge" data-variant="warning">KI meldet unlesbaren Text</span>':'')));
  if(o.nach_pass1) b.push(knoten('OCR-Nachlauf', o.nachlauf_fehler?'Fehler':o.nachlauf_verworfen?'verworfen':'nachgeholt', o.nachlauf_fehler?'destructive':'info',
    txt(o.nach_pass1.join('; '))+(o.nachlauf_verworfen?' · '+txt(o.nachlauf_verworfen):'')));
  const kname=((k.ergebnis||'').match(/'([^']*)'/)||[])[1]||k.vorschlag||'—';
  const kart=(k.ergebnis||'').startsWith('NEU')?'neu angelegt':(k.ergebnis||'').startsWith('exakt')?'bekannt':(k.ergebnis||'—');
  b.push(knoten('Korrespondent', kart+(kname!=='—'?': '+kname:''),
    (k.ergebnis||'').startsWith('NEU')?'warning':'success', k.pass2?'Rückfrage ans Modell: '+txt(JSON.stringify(k.pass2)):''));
  const felder=Object.entries(w.fields_ki||{});
  b.push(knoten('Geschrieben', t.error?'Fehler':(t._stage||'fertig'), t.error?'destructive':'success',
    (w.document_type?'Typ: '+txt(w.document_type)+'<br>':'')+(felder.length?felder.map(([n,v])=>txt(n)+': <b>'+txt(v)+'</b>').join('<br>'):'')+
    ((t.repair||[]).length?'<br>Korrekturrunden: '+t.repair.length:'')+(t.error?'<br>'+txt(t.error):'')));
  document.getElementById('lp-1').innerHTML='<div class="grid gap-2">'+b.map((k,i)=>k.replace('§',(i+1)+' ·')).join(PFEIL)+'</div>';
  document.getElementById('lp-2').innerHTML='<p class="mb-2 font-semibold">System</p>'+code(p1.system||'—')+'<p class="mt-4 mb-2 font-semibold">Nachricht</p>'+code(p1.user||'—');
  document.getElementById('lp-3').innerHTML='<p class="mb-2 font-semibold">Antwort der KI</p>'+code(r)+'<p class="mt-4 mb-2 font-semibold">Geschrieben</p>'+code(w);
  document.getElementById('lp-4').innerHTML=o.excerpt?'<div class="grid gap-2 text-sm">'+md(o.excerpt)+'</div>':'<p class="text-muted-foreground">Kein OCR-Text in diesem Lauf (der Paperless-Text wurde verwendet).</p>';
}
setzeFilter(F,true); verlauf(); laufend(); setInterval(laufend,5000); setInterval(()=>{ if(!document.getElementById('lauf').open) laden(); },30000);
"""


def _pfeil_js() -> str:
    import json
    return json.dumps(symbol("arrow-down", "size-10"))


_JS_AKTIVITAET = _JS_AKTIVITAET.replace("%PFEIL%", _pfeil_js())


# ---------------------------------------------------------------- Ablauf & Prompt
# Die Knoten des Ablaufs. Jeder nennt die Einstellungen, die ihn steuern — ein Klick auf den
# Knoten öffnet genau diese zum Bearbeiten (wie ein Knoten in n8n). `entscheidung` zeigt die
# beiden Zweige. Schlüssel mit Punkt liegen verschachtelt (ocr_regeln.max_muell_anteil).
KNOTEN = [
    {"id": "ausloeser", "titel": "Auslöser", "art": "schritt",
     "text": "Automatisch nach dem Import (Post-Consume) · manuell im Panel · aus Paperless per "
             "KI-/OCR-Knopf bzw. Tag und Hinweisfeld.",
     "felder": [("redo_tag", "Tag „neu klassifizieren“"), ("ocr_tag", "Tag „nur OCR“"),
                ("hinweis_field", "Hinweisfeld")]},
    {"id": "vorpruefung", "titel": "Schon klassifiziert?", "art": "entscheidung",
     "ja": "überspringen (Schleifenschutz) — Knöpfe und Panel umgehen das",
     "nein": "weiter",
     "felder": [("enabled", "Klassifizierer aktiv"), ("marker_tag", "Marker-Tag")]},
    {"id": "ocr", "titel": "Text brauchbar? (Regeln)", "art": "entscheidung",
     "ja": "Paperless-Text verwenden", "nein": "Mistral-OCR liest das Dokument neu",
     "felder": [("ocr_enabled", "OCR erlaubt"), ("ocr_always", "Immer OCR (kostet)"),
                ("ocr_model", "OCR-Modell"), ("ocr_min_len", "Mindestlänge (Zeichen)"),
                ("ocr_regeln.min_schluesselwoerter", "Mindestens bekannte Wörter"),
                ("ocr_regeln.max_zeichen_je_wort", "Höchstens Zeichen je echtem Wort"),
                ("ocr_regeln.max_muell_anteil", "Höchstanteil Zeichensalat (0–1)"),
                ("ocr_regeln.schluesselwoerter", "Bekannte Wörter")]},
    {"id": "pass0", "titel": "Pass 0 — Absender & Kandidaten", "art": "schritt",
     "text": "Ein kurzer Aufruf zieht den Absender aus Titel und Textanfang; per Namensabgleich "
             "gegen alle Korrespondenten gehen die wahrscheinlichsten mit Kontext an Pass 1.",
     "felder": [("korrespondent_beispiele", "Beispielpaare für den Abgleich")]},
    {"id": "pass1", "titel": "Pass 1 — Analyse (Prompt)", "art": "prompt",
     "felder": [("system_prompt", "System-Prompt (leer = eingebaut; {TYPES}, {TAGBLOCK}/{TAGS})"),
                ("model", "Modell"), ("temperature", "Temperatur"),
                ("content_max_len", "Text bis (Zeichen)")]},
    {"id": "nachlauf", "titel": "KI zufrieden?", "art": "entscheidung",
     "ja": "weiter zum Korrespondenten", "nein": "OCR nachholen und Pass 1 wiederholen (nur wenn noch kein OCR lief)",
     "felder": [("ocr_regeln.nach_ki_meldung", "Wenn die KI unlesbaren Text meldet"),
                ("ocr_regeln.wenn_kein_typ", "Wenn kein Dokumenttyp erkannt"),
                ("ocr_regeln.wenn_kein_korrespondent", "Wenn kein Korrespondent erkannt")]},
    {"id": "korrespondent", "titel": "Korrespondent bekannt?", "art": "entscheidung",
     "ja": "zuordnen", "nein": "Rückfrage ans Modell, sonst neu anlegen",
     "felder": []},
    {"id": "schreiben", "titel": "Zurückschreiben", "art": "schritt",
     "text": "Typ, Korrespondent, Datum und Felder nach Paperless; lehnt Paperless einen Wert ab, "
             "korrigiert die KI in derselben Unterhaltung.",
     "felder": [("manual_fields", "Felder, die die KI nie anfasst"), ("tagging_enabled", "KI vergibt Tags"),
                ("reserved_tags", "Reservierte Tags"), ("summary_field", "Feld für die Zusammenfassung"),
                ("unsicher_tag", "Tag bei Unsicherheit")]},
    {"id": "nachbearbeitung", "titel": "Nachbearbeitung", "art": "schritt",
     "text": "Optionales Skript nach dem Schreiben — für alles, was nur diese Installation braucht.",
     "felder": [("nachbearbeitung", "Skript-Pfad")]},
]


def ablauf() -> str:
    import json
    pfeil = f'<div class="flex justify-center text-muted-foreground">{symbol("arrow-down", "size-12")}</div>'
    teile = []
    for k in KNOTEN:
        bearbeiten = (f'<button type="button" class="btn" data-variant="outline" data-size="sm" '
                      f'onclick="event.stopPropagation();bearbeiten(\'{k["id"]}\')">{symbol("pencil")}Bearbeiten</button>'
                      if k["felder"] else "")
        if k["art"] == "entscheidung":
            innen = (f'<section class="grid grid-cols-2 gap-3">'
                     f'<div class="rounded-md border p-3"><span class="badge" data-variant="success">ja</span>'
                     f'<p class="mt-2 text-sm">{k["ja"]}</p></div>'
                     f'<div class="rounded-md border p-3"><span class="badge" data-variant="warning">nein</span>'
                     f'<p class="mt-2 text-sm">{k["nein"]}</p></div></section>'
                     f'<section class="text-muted-foreground text-sm" id="wert-{k["id"]}"></section>')
            marke = '<span class="badge" data-variant="outline">Entscheidung</span>'
        elif k["art"] == "prompt":
            innen = ('<section class="text-muted-foreground text-sm" id="wert-pass1"></section>'
                     '<section><pre class="code-block max-h-96 overflow-auto"><code id="prompt-vorschau">lädt…</code></pre></section>')
            marke = '<span class="badge" data-variant="info">KI</span>'
        else:
            innen = (f'<section class="text-sm">{k["text"]}</section>'
                     f'<section class="text-muted-foreground text-sm" id="wert-{k["id"]}"></section>')
            marke = '<span class="badge" data-variant="secondary">Schritt</span>'
        teile.append(
            f'<div class="card cursor-pointer hover:border-ring" data-size="sm" id="k-{k["id"]}" '
            f'onclick="bearbeiten(\'{k["id"]}\')">'
            f'<header class="flex flex-wrap items-center justify-between gap-2">'
            f'<h2 class="flex items-center gap-2">{marke}{k["titel"]}</h2>{bearbeiten}</header>{innen}</div>')
    fluss = pfeil.join(teile)
    editor = dialog("knoten", "Knoten bearbeiten", '<div id="knoten-felder" class="grid gap-4"></div>',
                    fuss=('<span id="knoten-meldung" class="text-muted-foreground text-sm"></span>'
                          '<button type="button" class="btn" data-variant="outline" onclick="this.closest(\'dialog\').close()">Abbrechen</button>'
                          '<button type="button" class="btn" onclick="speichern()">Speichern</button>'))
    knoten_js = json.dumps({k["id"]: {"titel": k["titel"], "felder": k["felder"]} for k in KNOTEN}, ensure_ascii=False)
    return (kopf("Ablauf & Prompt",
                 "So läuft ein Dokument durch paperlaiss. Ein Klick auf einen Knoten öffnet seine Einstellungen.")
            + f'<div class="mx-auto grid max-w-3xl gap-2">{fluss}</div>' + editor
            + "<script>" + _JS_GRUND + "const KNOTEN=" + knoten_js + ";" + _JS_ABLAUF + "</script>")


_JS_ABLAUF = r"""
let CFG={}, AKTIV=null;
function wert(pfad){return pfad.split('.').reduce((o,k)=>o==null?undefined:o[k],CFG)}
function kurz(v){ if(v===true) return 'an'; if(v===false) return 'aus'; if(v==null||v==='') return '—';
  if(Array.isArray(v)) return v.length?v.slice(0,6).map(String).join(', ')+(v.length>6?' …':''):'—';
  if(typeof v==='object') return JSON.stringify(v).slice(0,80); return String(v).slice(0,80); }
function zeigeWerte(){
  for(const [id,k] of Object.entries(KNOTEN)){
    const el=document.getElementById('wert-'+id); if(!el||!k.felder.length) continue;
    el.innerHTML=k.felder.filter(([p])=>p!=='system_prompt').map(([p,n])=>txt(n)+': <b>'+txt(kurz(wert(p)))+'</b>').join(' · ');
  }
}
async function laden(){
  try{ CFG=await holen('/api/config'); zeigeWerte(); }catch(e){}
  try{ const v=await holen('/api/prompt-vorschau'); document.getElementById('prompt-vorschau').textContent=v.system||'';
  }catch(e){ document.getElementById('prompt-vorschau').textContent='Vorschau nicht verfügbar: '+e.message; }
}
function feldHtml(pfad,name){
  const v=wert(pfad), id='f-'+pfad.replace(/\W/g,'_');
  if(typeof v==='boolean') return '<div class="field" role="group" data-orientation="horizontal"><input class="input" type="checkbox" role="switch" id="'+id+'"'+(v?' checked':'')+'><label class="label" for="'+id+'">'+txt(name)+'</label></div>';
  let e;
  if(pfad==='system_prompt') e='<textarea class="textarea max-h-96 font-mono" rows="18" id="'+id+'">'+txt(v)+'</textarea>';
  // Textlisten: ein Eintrag je Zeile, Leerzeichen bleiben (' der ' ist nicht 'der').
  else if(Array.isArray(v)&&v.every(x=>typeof x==='string')) e='<textarea class="textarea max-h-48 font-mono" rows="5" id="'+id+'">'+txt(v.join('\n'))+'</textarea><p class="text-muted-foreground text-sm">Ein Eintrag je Zeile.</p>';
  else if(Array.isArray(v)||(v&&typeof v==='object')) e='<textarea class="textarea max-h-48 font-mono" rows="5" id="'+id+'">'+txt(JSON.stringify(v,null,1))+'</textarea>';
  else if(typeof v==='number') e='<input class="input" type="number" step="any" id="'+id+'" value="'+txt(v)+'">';
  else e='<input class="input" id="'+id+'" value="'+txt(v??'')+'">';
  return '<div class="field" role="group"><label class="label" for="'+id+'">'+txt(name)+'</label>'+e+'</div>';
}
function bearbeiten(id){
  const k=KNOTEN[id]; if(!k||!k.felder.length) return; AKTIV=id;
  document.getElementById('knoten-titel').textContent=k.titel;
  document.getElementById('knoten-felder').innerHTML=k.felder.map(([p,n])=>feldHtml(p,n)).join('');
  document.getElementById('knoten-meldung').textContent='';
  document.getElementById('knoten').showModal();
}
async function speichern(){
  const k=KNOTEN[AKTIV], body={}, meld=document.getElementById('knoten-meldung');
  try{
    for(const [p] of k.felder){
      const el=document.getElementById('f-'+p.replace(/\W/g,'_')), alt=wert(p); let v;
      if(typeof alt==='boolean') v=el.checked;
      else if(Array.isArray(alt)&&alt.every(x=>typeof x==='string')) v=el.value.split('\n').filter(x=>x.trim()!=='');
      else if(Array.isArray(alt)||(alt&&typeof alt==='object')) v=JSON.parse(el.value||'null');
      else if(typeof alt==='number') v=Number(el.value);
      else v=el.value;
      // Verschachtelt (ocr_regeln.x): das ganze Wörterbuch schicken, sonst ginge der Rest verloren.
      if(p.includes('.')){ const [a,b]=p.split('.'); body[a]=body[a]||{...(CFG[a]||{})}; body[a][b]=v; } else body[p]=v;
    }
    const d=await senden('/api/config',body);
    meld.textContent=(d.uebergangen||[]).length?'übergangen: '+d.uebergangen.join(', '):'gespeichert';
    await laden(); if(!(d.uebergangen||[]).length) setTimeout(()=>document.getElementById('knoten').close(),500);
  }catch(e){ meld.textContent='Fehler: '+e.message; }
}
laden();
"""


# ---------------------------------------------------------------- Einstellungen
def einstellungen() -> str:
    return (kopf("Einstellungen", "Alle Werte der classify-config.json. Schlüssel gehören in die Umgebung, nicht hierher.",
                 '<button type="button" class="btn" onclick="sichern()">'
                 f'{symbol("save")}Speichern</button><span id="meld" class="text-muted-foreground text-sm"></span>')
            + '<div id="felder" class="mx-auto grid max-w-3xl gap-4"><p class="text-muted-foreground">lädt…</p></div>'
            + "<script>" + _JS_GRUND + _JS_EINSTELLUNGEN + "</script>")


_JS_EINSTELLUNGEN = r"""
let FELDER=[];
async function laden(){
  const d=await holen('/api/config/schema'); FELDER=d.felder;
  document.getElementById('felder').innerHTML=FELDER.map(f=>{
    const id='f_'+f.name;
    if(f.typ==='bool') return '<div class="card" data-size="sm"><section><div class="field" role="group" data-orientation="horizontal"><input class="input" type="checkbox" role="switch" id="'+id+'"'+(f.wert?' checked':'')+'><label class="label" for="'+id+'">'+txt(f.name)+'</label></div></section></div>';
    let e;
    if(f.typ==='text') e='<textarea class="textarea font-mono" rows="8" id="'+id+'">'+txt(f.wert)+'</textarea>';
    else if(f.typ==='json') e='<textarea class="textarea font-mono" rows="4" id="'+id+'">'+txt(JSON.stringify(f.wert,null,1))+'</textarea>';
    else e='<input class="input" id="'+id+'" value="'+txt(f.wert)+'">';
    return '<div class="card" data-size="sm"><section><div class="field" role="group"><label class="label" for="'+id+'">'+txt(f.name)+'</label>'+e+'</div></section></div>';
  }).join('');
}
async function sichern(){
  const body={}, meld=document.getElementById('meld');
  for(const f of FELDER){ const el=document.getElementById('f_'+f.name); body[f.name]=f.typ==='bool'?el.checked:el.value; }
  try{ const d=await senden('/api/config',body);
    meld.textContent=(d.uebergangen||[]).length?'übergangen: '+d.uebergangen.join(', '):'gespeichert';
  }catch(e){ meld.textContent='Fehler: '+e.message; }
}
laden();
"""
