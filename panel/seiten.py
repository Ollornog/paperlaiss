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


# Schritte: EINE Darstellung für den Ablauf (Vorlage, bearbeitbar) und den Lauf eines Dokuments
# (echte Werte). Jeder Schritt: Nummer, Art (Paperless/Schritt/KI/Entscheidung als Wort, keine
# Sonderformen), Titel, Regeln „wenn … → …", und zum Aufklappen Eingabe und Ausgabe — bei KI-
# Schritten der Prompt und die Antwort.
_JS_SCHRITTE = r"""
const CHEV=%CHEV%, PFEIL_K=%PFEILK%;
const ART={paperless:['Paperless','info'],code:['Schritt','secondary'],ki:['KI',''],entscheidung:['Entscheidung','outline'],grenze:['','']};
// Lesbar statt Code: Text mit Absätzen und Zeilenumbrüchen in normaler Schrift, Objekte als Tabelle.
function prosa(t){
  const abs=String(t||'').trim().split(/\n\s*\n/).map(a=>'<p>'+txt(a).replace(/\n/g,'<br>')+'</p>').join('');
  return '<div class="grid max-h-96 gap-2 overflow-y-auto rounded-md border bg-muted/40 p-3 leading-relaxed">'+(abs||'<p>—</p>')+'</div>';
}
function wertText(v){ if(v===null||v===undefined) return '<span class="text-muted-foreground">leer</span>';
  if(Array.isArray(v)) return v.length?v.map(x=>txt(typeof x==='object'?JSON.stringify(x):x)).join(', '):'<span class="text-muted-foreground">keine</span>';
  if(typeof v==='object') return txt(JSON.stringify(v)); if(typeof v==='boolean') return v?'ja':'nein'; return txt(v); }
function tabelle(obj,kopf){
  const zeilen=[]; const rein=(o,vor)=>{ for(const [k,v] of Object.entries(o||{})){
      if(v&&typeof v==='object'&&!Array.isArray(v)) rein(v,vor+k+' · '); else zeilen.push([vor+k,v]); } };
  rein(obj,'');
  if(!zeilen.length) return '<p class="text-muted-foreground">—</p>';
  return '<div class="overflow-x-auto"><table class="table"><thead><tr><th>'+txt((kopf||['Feld','Wert'])[0])+'</th><th>'+txt((kopf||['Feld','Wert'])[1])+'</th></tr></thead><tbody>'+
    zeilen.map(([k,v])=>'<tr><td class="whitespace-nowrap font-medium">'+txt(k)+'</td><td>'+wertText(v)+'</td></tr>').join('')+'</tbody></table></div>';
}
function klapp(titel,inhalt,offen){return '<details class="min-w-0"'+(offen?' open':'')+'><summary>'+txt(titel)+CHEV+'</summary><div class="min-w-0">'+inhalt+'</div></details>'}
function schritt(o){
  if(o.art==='grenze') return '<div class="mx-auto w-fit rounded-full border bg-muted/40 px-6 py-2 text-center text-sm font-medium">'+txt(o.titel)+'</div>';
  const a=ART[o.art]||['',''];
  const badge='<span class="badge"'+(a[1]?' data-variant="'+a[1]+'"':'')+'>'+a[0]+'</span>';
  const erg=o.ergebnis?'<span class="badge" data-variant="'+(o.variante||'secondary')+'">'+txt(o.ergebnis)+'</span>':'';
  const regeln=(o.regeln||[]).length?'<ul class="grid gap-1">'+o.regeln.map(r=>'<li class="flex items-start gap-2"><span class="badge" data-variant="outline">'+txt(r[0])+'</span><span>'+r[1]+'</span></li>').join('')+'</ul>':'';
  // min-w-0: ein Grid-Kind ist sonst so breit wie sein längster Inhalt, Code liefe aus der Karte.
  const klappen=(o.klappen||[]).length?'<div class="accordion min-w-0" data-multiple>'+o.klappen.map(k=>klapp(k[0],k[1],k[2])).join('')+'</div>':'';
  return '<div class="card" data-size="sm"'+(o.id?' id="k-'+o.id+'"':'')+'><header class="flex flex-wrap items-center justify-between gap-2">'+
    '<h2 class="flex items-center gap-2"><span class="text-muted-foreground tabular-nums">'+(o.nr||'')+'</span>'+badge+txt(o.titel)+'</h2>'+
    '<div class="flex items-center gap-2">'+erg+(o.knopf||'')+'</div></header>'+
    '<section class="grid min-w-0 gap-3 text-sm">'+(o.text?'<p>'+o.text+'</p>':'')+regeln+klappen+'</section></div>';
}
function kette(liste){let n=0;return liste.map(o=>schritt(o.art==='grenze'?o:{...o,nr:++n})).join(PFEIL_K)}
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
    lauf = dialog("lauf", "Lauf", '<div id="lauf-schritte" class="grid gap-2"></div>')
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
        + "<script>" + _JS_GRUND + _JS_SCHRITTE_FERTIG + "const ARTEN=" + arten_js + ";" + _JS_AKTIVITAET + "</script>"
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
// ---- Lauf-Dialog: die Schritte dieses Laufs, mit Prompt und Antwort je KI-Aufruf ----
async function lauf(doc){
  if(!doc) return; const dlg=document.getElementById('lauf'), ziel=document.getElementById('lauf-schritte');
  document.getElementById('lauf-titel').textContent='Lauf · Dokument #'+doc;
  ziel.innerHTML='<p class="text-muted-foreground">lädt…</p>'; dlg.showModal();
  let t; try{ t=await holen('/api/trace/'+doc); }catch(e){ ziel.innerHTML='<p>Kein Ablauf gespeichert ('+txt(e.message)+'). Aufgezeichnet wird je Dokument der letzte Lauf.</p>'; return; }
  const o=t.ocr||{}, p0=t.pass0||{}, p1=t.pass1||{}, r=p1.response||{}, k=t.correspondent||{}, w=t.writeback||{};
  const L=[{art:'grenze',titel:(t.trigger||'automatisch')+' · '+(t.ts||'')}];
  if(t.hinweis) L.push({art:'code',titel:'Hinweis vom Knopf',text:txt(t.hinweis)});
  L.push({art:'entscheidung',titel:'Text brauchbar? — sonst Mistral-OCR',
    ergebnis:o.triggered?(o.error?'OCR-Fehler':o.verworfen?'OCR verworfen':'OCR gelesen'):'Paperless-Text',
    variante:o.error?'destructive':o.triggered?'info':'success',
    text:txt(o.grund||'')+(o.chars?' · '+o.chars+' Zeichen':'')+(o.verworfen?' · '+txt(o.verworfen):'')+(o.error?' · '+txt(o.error):''),
    klappen:o.excerpt?[['Ausgabe — gelesener Text','<div class="grid gap-2">'+md(o.excerpt)+'</div>']]:[]});
  if(t.pass0) L.push({art:'ki',titel:'Pass 0 — Absender',ergebnis:p0.vorschlag||'keiner',
    text:'Quelle: '+txt(p0.quelle||'—')+' · Kandidaten: '+(p0.kandidaten||[]).map(txt).join(', '),
    klappen:p0.system?[['Eingabe — Anweisung',prosa(p0.system)],['Eingabe — Nachricht',prosa(p0.user||'')],['Ausgabe',tabelle(p0.response||{})]]:[]});
  L.push({art:'ki',titel:'Pass 1 — Analyse',ergebnis:r.document_type||'kein Typ',variante:r.document_type?'success':'warning',
    text:'Korrespondent: '+txt(r.correspondent||'—')+' · Datum: '+txt(r.document_date||'—')+(r.needs_ocr?' · meldet unlesbaren Text':''),
    klappen:[['Eingabe — System-Prompt',prosa(p1.system||'—')],['Eingabe — Nachricht',prosa(p1.user||'—')],['Ausgabe',tabelle(r),true]]});
  if(o.nach_pass1) L.push({art:'entscheidung',titel:'OCR-Nachlauf',ergebnis:o.nachlauf_fehler?'Fehler':o.nachlauf_verworfen?'verworfen':'nachgeholt',
    variante:o.nachlauf_fehler?'destructive':'info',text:txt(o.nach_pass1.join('; '))+(o.nachlauf_verworfen?' · '+txt(o.nachlauf_verworfen):'')});
  const kname=((k.ergebnis||'').match(/'([^']*)'/)||[])[1]||k.vorschlag||'—';
  const kart=(k.ergebnis||'').startsWith('NEU')?'neu angelegt':(k.ergebnis||'').startsWith('exakt')?'bekannt':(k.ergebnis||'—');
  L.push({art:'entscheidung',titel:'Korrespondent zuordnen',ergebnis:kart+(kname!=='—'?': '+kname:''),
    variante:(k.ergebnis||'').startsWith('NEU')?'warning':'success',
    klappen:k.pass2?[['Pass 2 — Eingabe'+(k.pass2.im_gespraech?' (angehängt an die Pass-1-Unterhaltung)':''),prosa((k.pass2.system?k.pass2.system+'\n\n':'')+(k.pass2.user||''))],['Pass 2 — Ausgabe',tabelle(k.pass2.response||{})]]:[]});
  const felder=Object.entries(w.fields_ki||{});
  L.push({art:'paperless',titel:'Nach Paperless geschrieben',ergebnis:t.error?'Fehler':(t._stage||'fertig'),variante:t.error?'destructive':'success',
    text:(w.document_type?'Typ: '+txt(w.document_type)+' · ':'')+(felder.length?felder.length+' Felder':'')+((t.repair||[]).length?' · Korrekturrunden: '+t.repair.length:'')+(t.error?' · '+txt(t.error):''),
    klappen:[['Ausgabe — geschrieben',tabelle(w)]]});
  L.push({art:'grenze',titel:'Ende'});
  ziel.innerHTML=kette(L);
}
setzeFilter(F,true); verlauf(); laufend(); setInterval(laufend,5000); setInterval(()=>{ if(!document.getElementById('lauf').open) laden(); },30000);
"""





# ---------------------------------------------------------------- Ablauf & Prompt
# Das Diagramm folgt den üblichen Flussdiagramm-Regeln (ISO 5807): EINE Form je Bedeutung,
# Fluss von oben nach unten, Zweige mit „ja"/„nein" beschriftet —
#   Oval        Start / Ende
#   Rechteck    Schritt (Code, kein Modell)
#   Daten       Lesen/Schreiben in Paperless (blau hinterlegt; ISO: Parallelogramm)
#   Raute       Entscheidung
#   KI-Knoten   ein Modellaufruf: EINGABE (Prompt) → Modell → AUSGABE (was zurückkommt)
# Jeder Knoten mit Einstellungen öffnet sie per Klick (wie ein Knoten in n8n). Schlüssel mit
# Punkt liegen verschachtelt (ocr_regeln.max_muell_anteil).
KNOTEN_FELDER = {
    "vorpruefung": ("Schon klassifiziert?", [("enabled", "Klassifizierer aktiv"), ("marker_tag", "Marker-Tag")]),
    "ocr": ("Text brauchbar?", [("ocr_enabled", "OCR erlaubt"), ("ocr_always", "Immer OCR (kostet)"),
                                ("ocr_model", "OCR-Modell"), ("ocr_min_len", "Mindestlänge (Zeichen)"),
                                ("ocr_regeln.min_schluesselwoerter", "Mindestens bekannte Wörter"),
                                ("ocr_regeln.max_zeichen_je_wort", "Höchstens Zeichen je echtem Wort"),
                                ("ocr_regeln.max_muell_anteil", "Höchstanteil Zeichensalat (0–1)"),
                                ("ocr_regeln.schluesselwoerter", "Bekannte Wörter")]),
    "pass0": ("Pass 0 — Absender", [("korrespondent_beispiele", "Beispielpaare für den Abgleich")]),
    "pass1": ("Pass 1 — Analyse", [("system_prompt", "System-Prompt (leer = eingebaut; {TYPES}, {TAGBLOCK}/{TAGS})"),
                                   ("model", "Modell"), ("temperature", "Temperatur"),
                                   ("content_max_len", "Text bis (Zeichen)")]),
    "nachlauf": ("Text lesbar laut KI?", [("ocr_regeln.nach_ki_meldung", "Wenn die KI unlesbaren Text meldet"),
                                          ("ocr_regeln.wenn_kein_typ", "Wenn kein Dokumenttyp erkannt"),
                                          ("ocr_regeln.wenn_kein_korrespondent", "Wenn kein Korrespondent erkannt")]),
    "schreiben": ("Nach Paperless schreiben", [("manual_fields", "Felder, die die KI nie anfasst"),
                                               ("tagging_enabled", "KI vergibt Tags"),
                                               ("reserved_tags", "Reservierte Tags"),
                                               ("summary_field", "Feld für die Zusammenfassung"),
                                               ("unsicher_tag", "Tag bei Unsicherheit")]),
    "nachbearbeitung": ("Eigenes Skript danach", [("nachbearbeitung", "Skript-Pfad")]),
}


def ablauf() -> str:
    import json
    editor = dialog("knoten", "Einstellungen", '<div id="knoten-felder" class="grid gap-4"></div>',
                    fuss=('<span id="knoten-meldung" class="text-muted-foreground text-sm"></span>'
                          '<button type="button" class="btn" data-variant="outline" onclick="this.closest(\'dialog\').close()">Abbrechen</button>'
                          '<button type="button" class="btn" onclick="speichern()">Speichern</button>'))
    knoten_js = json.dumps({k: {"titel": t, "felder": f} for k, (t, f) in KNOTEN_FELDER.items()}, ensure_ascii=False)
    return (kopf("Ablauf & Prompt",
                 "Jeder Schritt, den ein Dokument durchläuft — aufklappbar mit Eingabe und Ausgabe, bei der KI mit Prompt "
                 "und Antwortformat. Der Prompt ist hier bearbeitbar.")
            + '<div id="schritte" class="mx-auto grid max-w-3xl gap-2"><p class="text-muted-foreground">lädt…</p></div>' + editor
            + "<script>" + _JS_GRUND + _JS_SCHRITTE_FERTIG + "const KNOTEN=" + knoten_js + ";" + _JS_ABLAUF + "</script>")


_JS_ABLAUF = r"""
let CFG={}, V={}, AKTIV=null;
function wert(pfad){return pfad.split('.').reduce((o,k)=>o==null?undefined:o[k],CFG)}
function an(b){return b?'an':'aus'}
function knopf(id){return '<button type="button" class="btn" data-variant="outline" data-size="sm" onclick="bearbeiten(\''+id+'\')">'+%STIFT%+'Einstellungen</button>'}
function zeichnen(){
  const o=CFG.ocr_regeln||{}, mz=o.min_zeichen??CFG.ocr_min_len;
  const L=[
    {art:'grenze',titel:'Start — nach dem Import · KI-Knopf in Paperless · Panel'},
    {art:'paperless',titel:'Dokument laden',text:'Titel, Text, Metadaten und Felder aus Paperless.'},
    {art:'entscheidung',id:'vorpruefung',titel:'Schon klassifiziert?',knopf:knopf('vorpruefung'),
      regeln:[['Klassifizierer '+an(CFG.enabled),'aus: automatische Läufe enden hier'],
              ['automatisch + Tag „'+txt(CFG.marker_tag)+'“','überspringen (Schleifenschutz)'],
              ['KI-Knopf / Panel','immer weiter']]},
    {art:'entscheidung',id:'ocr',titel:'Text brauchbar? — sonst Mistral-OCR',knopf:knopf('ocr'),
      regeln:[['KI-Knopf','immer OCR'],['kürzer als '+mz+' Zeichen','OCR'],
              ['weniger als '+o.min_schluesselwoerter+' bekannte Wörter','OCR'],
              ['mehr als '+Math.round((o.max_muell_anteil||0)*100)+' % Zeichensalat','OCR'],
              ['Immer-OCR '+an(CFG.ocr_always),'an: jedes Dokument'],['sonst','Paperless-Text verwenden']],
      klappen:[['Eingabe','<p>Das Dokument als PDF an <b>'+txt(CFG.ocr_model)+'</b>.</p>'],['Ausgabe','<p>Der Text als Markdown (Überschriften, Tabellen) — ersetzt den Paperless-Text.</p>']]},
    {art:'ki',id:'pass0',titel:'Pass 0 — Absender erkennen',knopf:knopf('pass0'),
      text:'Modell <b>'+txt(CFG.model)+'</b>, kurzer Aufruf.',
      regeln:[['Absender-Mail passt zu einer bekannten Domain','Aufruf entfällt']],
      klappen:[['Eingabe — Anweisung',prosa(V.pass0_system||'')],['Eingabe — Nachricht',prosa('TITEL: <Titel>\n\nINHALT:\n<die ersten 2500 Zeichen>')],
               ['Ausgabe',tabelle({correspondent:'Name des Absenders oder leer'},['Feld','Bedeutung'])]]},
    {art:'code',titel:'Kandidaten suchen',text:'Namensabgleich des Absenders gegen alle Korrespondenten (auch Aliase). Die besten gehen samt Kontext an Pass 1.'},
    {art:'ki',id:'pass1',titel:'Pass 1 — Analyse',knopf:knopf('pass1'),
      text:'Modell <b>'+txt(CFG.model)+'</b> · Temperatur '+txt(CFG.temperature)+' · Text bis '+txt(CFG.content_max_len)+' Zeichen.',
      klappen:[['Eingabe — System-Prompt (bearbeitbar)','<textarea class="textarea max-h-96 w-full font-mono" rows="12" id="prompt-vorlage">'+txt(CFG.system_prompt||'')+'</textarea>'+
                  '<div class="mt-2 flex items-center gap-2"><button type="button" class="btn" data-size="sm" onclick="promptSpeichern()">Prompt speichern</button>'+
                  '<span id="prompt-meldung" class="text-muted-foreground text-sm">Leer = eingebauter Prompt. {TYPES} = Dokumenttypen, {TAGBLOCK} = Tag-Liste.</span></div>',true],
               ['Eingabe — so geht der System-Prompt an die KI',prosa(V.system||'')],
               ['Eingabe — Nachricht je Dokument',prosa('HINWEIS vom KI-Knopf (falls eingegeben)\nMÖGLICHE KORRESPONDENTEN — die Kandidaten aus Pass 0, je mit Kontext\nMETADATEN: hinzugefügt · Dokumentdatum · Dateiname\nVERFÜGBARE FELDER: '+(V.ki_felder||[]).join(', ')+'\nTITEL\n\nINHALT (bis '+txt(CFG.content_max_len)+' Zeichen)')],
               ['Ausgabe',tabelle({document_type:'Dokumenttyp aus der Liste, oder leer',correspondent:'Name des Absenders, oder leer',
                  fields:'je Feld: Wert · leer (löschen) · „BEHALTEN“',document_date:'tatsächliches Dokumentdatum (JJJJ-MM-TT)',
                  summary:'kurze Zusammenfassung',tags:'Tags aus der Liste (nur bei aktivem Tagging)',needs_ocr:'ja, wenn der Text unlesbar ist'},['Feld','Bedeutung'])]]},
    {art:'entscheidung',id:'nachlauf',titel:'Text lesbar laut KI?',knopf:knopf('nachlauf'),
      regeln:[['KI meldet unlesbaren Text ('+an(o.nach_ki_meldung)+')','OCR nachholen, Pass 1 wiederholen'],
              ['kein Dokumenttyp ('+an(o.wenn_kein_typ)+')','ebenso'],['kein Korrespondent ('+an(o.wenn_kein_korrespondent)+')','ebenso'],
              ['OCR lief schon','kein zweites Mal']]},
    {art:'entscheidung',titel:'Korrespondent zuordnen',
      regeln:[['Name passt exakt','zuordnen'],['ähnliche Kandidaten','Pass 2: dieselbe KI-Unterhaltung wie Pass 1 bekommt die Kandidaten und wählt einen oder keinen'],['kein Treffer','neu anlegen']],
      klappen:[['Pass 2 — Eingabe (eine weitere Nachricht in der Pass-1-Unterhaltung)',prosa((V.pass2_system||'')+"\nDein vorgeschlagener Absender: <Name>\nBestehende Korrespondenten, die in Frage kommen: <Namen>")],
               ['Pass 2 — Ausgabe',tabelle({match:'exakter Name aus der Kandidatenliste, oder leer'},['Feld','Bedeutung'])]]},
    {art:'paperless',id:'schreiben',titel:'Nach Paperless schreiben',knopf:knopf('schreiben'),
      text:'Typ, Korrespondent, Datum, Felder'+(CFG.tagging_enabled?', Tags':'')+'; Tag „'+txt(CFG.marker_tag)+'“. Nie angefasst: '+((CFG.manual_fields||[]).map(txt).join(', ')||'—')+'.',
      regeln:[['Paperless lehnt einen Wert ab','Selbstkorrektur: die Fehlermeldung geht in dieselbe KI-Unterhaltung, die KI korrigiert, es wird erneut geschrieben (mehrere Runden)']]},
    {art:'code',id:'nachbearbeitung',titel:'Eigenes Skript danach (optional)',knopf:knopf('nachbearbeitung'),
      text:CFG.nachbearbeitung?'Skript <b>'+txt(CFG.nachbearbeitung)+'</b> bekommt das Ergebnis.':'nicht eingerichtet — nur für Zusatzschritte einer einzelnen Installation, etwa eine Verknüpfung in ein eigenes System'},
    {art:'grenze',titel:'Ende'}];
  document.getElementById('schritte').innerHTML=kette(L);
}
async function laden(){
  try{ CFG=await holen('/api/config'); }catch(e){}
  try{ V=await holen('/api/prompt-vorschau'); }catch(e){ V={system:'Vorschau nicht verfügbar: '+e.message}; }
  zeichnen();
}
async function promptSpeichern(){
  const m=document.getElementById('prompt-meldung');
  try{ const d=await senden('/api/config',{system_prompt:document.getElementById('prompt-vorlage').value});
    m.textContent=(d.uebergangen||[]).length?'übergangen: '+d.uebergangen.join(', '):'gespeichert'; await laden();
  }catch(e){ m.textContent='Fehler: '+e.message; }
}
function feldHtml(pfad,name){
  const v=wert(pfad), id='f-'+pfad.replace(/\W/g,'_');
  if(typeof v==='boolean') return '<div class="field" role="group" data-orientation="horizontal"><input class="input" type="checkbox" role="switch" id="'+id+'"'+(v?' checked':'')+'><label class="label" for="'+id+'">'+txt(name)+'</label></div>';
  let e;
  if(pfad==='system_prompt') e='<textarea class="textarea max-h-96 font-mono" rows="18" id="'+id+'">'+txt(v)+'</textarea>';
  else if(Array.isArray(v)&&v.every(x=>typeof x==='string')) e='<textarea class="textarea max-h-48 font-mono" rows="5" id="'+id+'">'+txt(v.join('\n'))+'</textarea><p class="text-muted-foreground text-sm">Ein Eintrag je Zeile.</p>';
  else if(Array.isArray(v)||(v&&typeof v==='object')) e='<textarea class="textarea max-h-48 font-mono" rows="5" id="'+id+'">'+txt(JSON.stringify(v,null,1))+'</textarea>';
  else if(typeof v==='number') e='<input class="input" type="number" step="any" id="'+id+'" value="'+txt(v)+'">';
  else e='<input class="input" id="'+id+'" value="'+txt(v??'')+'">';
  return '<div class="field" role="group"><label class="label" for="'+id+'">'+txt(name)+'</label>'+e+'</div>';
}
function bearbeiten(id){
  const k=KNOTEN[id]; if(!k) return; AKTIV=id;
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
      if(p.includes('.')){ const [a,b]=p.split('.'); body[a]=body[a]||{...(CFG[a]||{})}; body[a][b]=v; } else body[p]=v;
    }
    const d=await senden('/api/config',body);
    meld.textContent=(d.uebergangen||[]).length?'übergangen: '+d.uebergangen.join(', '):'gespeichert';
    await laden(); if(!(d.uebergangen||[]).length) setTimeout(()=>document.getElementById('knoten').close(),500);
  }catch(e){ meld.textContent='Fehler: '+e.message; }
}
laden();
"""



# ---------------------------------------------------------------- Info
def info() -> str:
    def link(href: str, text: str) -> str:
        return (f'<a class="btn" data-variant="outline" data-size="sm" href="{href}" rel="noopener">'
                f'{symbol("external-link")}{text}</a>')
    return (kopf("Info", "Was paperlaiss ist und wo es herkommt.",
                 link("https://github.com/Ollornog/paperlaiss", "paperlaiss auf GitHub"))
            + '<div class="mx-auto max-w-3xl">'
            + abschnitt("Was es macht", (
                '<div class="grid gap-3 text-sm">'
                '<p>paperlaiss ist eine Middleware für Paperless-ngx: Es liest neue Dokumente, lässt eine KI '
                '(Mistral) Dokumenttyp, Korrespondent, Datum und Felder bestimmen und schreibt das Ergebnis '
                'zurück — geerdet gegen den vorhandenen Bestand, damit keine erfundenen Korrespondenten oder '
                'Typen entstehen. Schwachen Text liest es vorher per Mistral-OCR neu.</p>'
                '<p>Stammdaten (Tags, Korrespondenten, Typen) bleiben in Paperless. Dieses Panel ist für den '
                'Fall da, dass etwas hängt oder eingestellt werden muss.</p></div>'))
            + abschnitt("So wird es benutzt", (
                '<ul class="grid gap-2 text-sm">'
                '<li><b>Automatisch</b> — nach jedem Import ruft Paperless paperlaiss auf (Post-Consume).</li>'
                '<li><b>KI-Knopf in Paperless</b> — in der Dokumentansicht und im Menü „Actions“ der '
                'Mehrfachauswahl: optional ein Hinweis, dann liest paperlaiss das Dokument per OCR neu und '
                'klassifiziert es neu.</li>'
                '<li><b>Aktivität</b> — was lief; eine Zeile zeigt den Lauf mit Prompt und Antwort der KI.</li>'
                '<li><b>Ablauf &amp; Prompt</b> — jeder Schritt mit Eingabe und Ausgabe; der Prompt ist dort bearbeitbar.</li>'
                '<li><b>Einstellungen</b> — alle Werte mit Erklärung.</li></ul>'))
            + abschnitt("Bausteine und Lizenzen", (
                '<ul class="grid gap-2 text-sm">'
                '<li>paperlaiss — MIT-Lizenz.</li>'
                '<li>Aussehen: <a class="underline" href="https://github.com/Ollornog/C22" rel="noopener">C22</a> '
                '(Basecoat, Tailwind; Schrift Inter unter SIL Open Font License).</li>'
                '<li>Anmeldung: <a class="underline" href="https://github.com/Ollornog/TinySesam" rel="noopener">TinySesam</a>.</li>'
                '<li>KI und Texterkennung: Mistral.</li>'
                '<li>Icon: <a class="underline" href="https://www.flaticon.com/authors/magnific" rel="noopener">'
                'Origami by Magnific – flaticon.com</a>.</li></ul>'))
            + '</div>')


# ---------------------------------------------------------------- Einstellungen
# Jede Einstellung mit Gruppe, Titel und Beschreibung. Schlüssel, die hier fehlen, erscheinen
# unter „Weitere" mit ihrem rohen Namen — so geht ein neuer Schlüssel nicht verloren, fällt aber
# auf. Verschachtelte Werte (ocr_regeln.x) werden einzeln gezeigt.
GRUPPEN = ["Allgemein", "KI-Modell & Prompt", "OCR", "Tags", "Felder", "Korrespondenten", "Erweitert"]
EINSTELLUNGEN = {
    "enabled": ("Allgemein", "Klassifizierer aktiv",
                "Hauptschalter. Aus: automatisch importierte Dokumente werden übersprungen. "
                "Der KI-Knopf in Paperless und das Panel funktionieren weiter."),
    "marker_tag": ("Allgemein", "Marker-Tag",
                   "Setzt paperlaiss nach jeder Klassifizierung. Ein Dokument mit diesem Tag wird beim "
                   "automatischen Lauf nicht noch einmal klassifiziert (Schleifenschutz)."),
    "model": ("KI-Modell & Prompt", "Modell", "Mistral-Modell für die Analyse (Pass 0, 1 und 2)."),
    "temperature": ("KI-Modell & Prompt", "Temperatur",
                    "Wie frei das Modell antwortet: 0 = immer gleich, höher = kreativer. Für Klassifizierung niedrig halten (0–0,2)."),
    "content_max_len": ("KI-Modell & Prompt", "Text bis (Zeichen)",
                        "So viel vom Dokumenttext geht an die KI. Mehr kostet mehr und ist selten nötig."),
    "system_prompt": ("KI-Modell & Prompt", "System-Prompt",
                      "Die Anweisung an die KI. Leer = eingebauter Prompt. Platzhalter: {TYPES} (Dokumenttypen), "
                      "{TAGBLOCK} oder {TAGS} (Tag-Liste). Fertig eingesetzt zu sehen unter „Ablauf & Prompt“."),
    "ocr_enabled": ("OCR", "OCR erlaubt", "Aus: paperlaiss liest nie per Mistral-OCR, auch nicht beim KI-Knopf."),
    "ocr_always": ("OCR", "Immer OCR", "Jedes Dokument per Mistral-OCR neu lesen, auch wenn der Text gut ist. Kostet je Seite."),
    "ocr_model": ("OCR", "OCR-Modell", "Mistral-Modell für die Texterkennung."),
    "ocr_min_len": ("OCR", "Mindestlänge (Zeichen)", "Kürzerer Text gilt als unbrauchbar und wird per OCR neu gelesen."),
    "ocr_regeln.min_schluesselwoerter": ("OCR", "Mindestens bekannte Wörter",
                                         "So viele Wörter aus der Liste „Bekannte Wörter“ muss der Text enthalten, sonst OCR."),
    "ocr_regeln.schluesselwoerter": ("OCR", "Bekannte Wörter",
                                     "Allerweltswörter, an denen lesbarer Text erkannt wird. Ein Eintrag je Zeile; "
                                     "Leerzeichen zählen („ der “ trifft nicht in „oder“)."),
    "ocr_regeln.max_zeichen_je_wort": ("OCR", "Höchstens Zeichen je echtem Wort",
                                       "Kommt auf so viele Zeichen weniger als ein echtes Wort, gilt der Text als Zeichensalat."),
    "ocr_regeln.max_muell_anteil": ("OCR", "Höchstanteil Zeichensalat",
                                    "Anteil (0–1) der Zeichen, die weder Buchstabe, Ziffer noch übliches Satzzeichen sind. Darüber: OCR."),
    "ocr_regeln.nach_ki_meldung": ("OCR", "OCR, wenn die KI unlesbaren Text meldet",
                                   "Nach der Analyse: meldet die KI Müll, wird per OCR neu gelesen und noch einmal analysiert."),
    "ocr_regeln.wenn_kein_typ": ("OCR", "OCR, wenn kein Dokumenttyp erkannt",
                                 "Nach der Analyse: ohne Typ wird per OCR neu gelesen und noch einmal analysiert."),
    "ocr_regeln.wenn_kein_korrespondent": ("OCR", "OCR, wenn kein Korrespondent erkannt",
                                           "Nach der Analyse: ohne Korrespondent wird per OCR neu gelesen und noch einmal analysiert."),
    "ocr_regeln.min_zeichen": ("OCR", "Mindestlänge (Regel)", "Wie „Mindestlänge“, hat Vorrang, wenn gesetzt."),
    "tagging_enabled": ("Tags", "KI vergibt Tags", "An: die KI wählt passende Tags aus dem Bestand. Aus: nur Typ, Korrespondent, Felder."),
    "tag_descriptions": ("Tags", "Tag-Beschreibungen",
                         "Kurze Beschreibung je Tag für die KI, als {\"Tagname\": \"Beschreibung\"}. Nur bei aktivem Tagging."),
    "reserved_tags": ("Tags", "Reservierte Tags",
                      "Tags, die die KI nie vergibt und die beim Schreiben erhalten bleiben (Status, Richtung …). Ein Eintrag je Zeile."),
    "unsicher_tag": ("Tags", "Tag bei Unsicherheit", "Wird gesetzt, wenn die KI einen neuen Tag vorschlägt. Leer = aus."),
    "manual_fields": ("Felder", "Felder, die die KI nie anfasst",
                      "Namen von Custom Fields, die nur von Hand gepflegt werden (z. B. Bezahlt-Am). Ein Eintrag je Zeile."),
    "summary_field": ("Felder", "Feld für die Zusammenfassung",
                      "Name eines Custom Fields (Langtext), in das die KI eine kurze Zusammenfassung schreibt. Leer = keine."),
    "mail_context_field": ("Felder", "Feld mit Mail-Kontext",
                           "Custom Field mit dem Anschreiben einer Mail; geht als Kontext an die KI. Leer = aus."),
    "mail_from_field": ("Felder", "Feld mit Absender-Mail",
                        "Custom Field mit der Absenderadresse; hilft, den Korrespondenten über die Domain zu finden. Leer = aus."),
    "korrespondent_beispiele": ("Korrespondenten", "Beispielpaare für den Abgleich",
                                "Paare [\"falsch geschrieben\", \"richtiger Name\"] — helfen der KI bei OCR-Fehlern im Absender."),
    "nachbearbeitung": ("Erweitert", "Eigenes Skript danach",
                        "Pfad zu einem Skript, das nach dem Schreiben läuft — für alles, was nur diese Installation braucht. Leer = aus."),
}


def einstellungen() -> str:
    import json
    return (kopf("Einstellungen", "Alle Werte der Konfiguration. Schlüssel (API-Keys) gehören in die Umgebung, nicht hierher.",
                 '<span id="meld" class="text-muted-foreground text-sm"></span>'
                 '<button type="button" class="btn" onclick="sichern()">'
                 f'{symbol("save")}Speichern</button>')
            + '<div id="felder" class="mx-auto grid max-w-3xl gap-6"><p class="text-muted-foreground">lädt…</p></div>'
            + "<script>" + _JS_GRUND + "const META=" + json.dumps(EINSTELLUNGEN, ensure_ascii=False)
            + ";const GRUPPEN=" + json.dumps(GRUPPEN + ["Weitere"], ensure_ascii=False) + ";" + _JS_EINSTELLUNGEN + "</script>")


_JS_EINSTELLUNGEN = r"""
let WERTE={};
function flach(cfg){ const out=[];
  for(const [k,v] of Object.entries(cfg)){
    if(v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(META).some(m=>m.startsWith(k+'.')))
      for(const [u,w] of Object.entries(v)) out.push([k+'.'+u,w]);
    else out.push([k,v]);
  } return out; }
function feld(pfad,v){
  const [gruppe,titel,text]=META[pfad]||['Weitere',pfad,''], id='f_'+pfad.replace(/\W/g,'_');
  const hilfe=text?'<p class="text-muted-foreground text-sm">'+txt(text)+'</p>':'';
  if(typeof v==='boolean') return [gruppe,'<div class="field" role="group" data-orientation="horizontal"><input class="input" type="checkbox" role="switch" id="'+id+'"'+(v?' checked':'')+'><label class="label" for="'+id+'">'+txt(titel)+'</label></div>'+hilfe];
  let e;
  if(pfad==='system_prompt') e='<textarea class="textarea max-h-96 font-mono" rows="12" id="'+id+'">'+txt(v)+'</textarea>';
  else if(Array.isArray(v)&&v.every(x=>typeof x==='string')) e='<textarea class="textarea max-h-48 font-mono" rows="4" id="'+id+'">'+txt(v.join('\n'))+'</textarea>';
  else if(v&&typeof v==='object') e='<textarea class="textarea max-h-48 font-mono" rows="4" id="'+id+'">'+txt(JSON.stringify(v,null,1))+'</textarea>';
  else if(typeof v==='number') e='<input class="input" type="number" step="any" id="'+id+'" value="'+txt(v)+'">';
  else e='<input class="input" id="'+id+'" value="'+txt(v??'')+'">';
  return [gruppe,'<div class="field" role="group"><label class="label" for="'+id+'">'+txt(titel)+'</label>'+e+hilfe+'</div>'];
}
async function laden(){
  WERTE=await holen('/api/config'); const je={};
  for(const [p,v] of flach(WERTE)){ const [g,h]=feld(p,v); (je[g]=je[g]||[]).push(h); }
  document.getElementById('felder').innerHTML=GRUPPEN.filter(g=>je[g]).map(g=>
    '<div class="card" data-size="sm"><header><h2>'+txt(g)+'</h2></header><section class="grid gap-5">'+je[g].join('')+'</section></div>').join('');
}
function lies(p,alt){ const el=document.getElementById('f_'+p.replace(/\W/g,'_'));
  if(typeof alt==='boolean') return el.checked;
  if(Array.isArray(alt)&&alt.every(x=>typeof x==='string')) return el.value.split('\n').filter(x=>x.trim()!=='');
  if(alt&&typeof alt==='object') return JSON.parse(el.value||'null');
  if(typeof alt==='number') return Number(el.value);
  return el.value; }
async function sichern(){
  const body={}, meld=document.getElementById('meld');
  try{
    for(const [p,alt] of flach(WERTE)){ const v=lies(p,alt);
      if(p.includes('.')){ const [a,b]=p.split('.'); body[a]=body[a]||{...(WERTE[a]||{})}; body[a][b]=v; } else body[p]=v; }
    const d=await senden('/api/config',body);
    meld.textContent=(d.uebergangen||[]).length?'übergangen: '+d.uebergangen.join(', '):'gespeichert';
    await laden();
  }catch(e){ meld.textContent='Fehler: '+e.message; }
}
laden();
"""


def _json(x):
    import json
    return json.dumps(x)


_JS_SCHRITTE_FERTIG = (_JS_SCHRITTE.replace("%CHEV%", _json(symbol("chevron-down")))
                       .replace("%PFEILK%", _json('<div class="flex justify-center text-muted-foreground">'
                                                  + symbol("arrow-down", "size-8") + "</div>")))
_JS_ABLAUF = _JS_ABLAUF.replace("%STIFT%", _json(symbol("pencil")))
