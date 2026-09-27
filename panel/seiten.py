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
async function holen(u,o){const r=await fetch((u[0]==='/'?PL_BASIS:'')+u,o);if(!r.ok)throw new Error(r.status+' '+(await r.text()).slice(0,200));return r.json()}
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
const CHEV=%CHEV%, CHEVK=%CHEVK%, SYMA=%SYMA%, PFEIL_K=%PFEILK%, PFEIL_I=%PFEILI%, SYME=%SYME%, SYM=%SYM%, SYMG=%SYMG%, SYMK=%SYMK%;
const ART={paperless:['Paperless','info','inbox'],code:['paperlaiss','outline','settings-2'],ki:['KI','','bot'],ocr:['Mistral-OCR','','file-text'],entscheidung:['Entscheidung','outline','git-branch'],grenze:['','','']};
// Eingesetzte Werte und Platzhalter farbig hinterlegt — so sieht man, was fest im Prompt steht
// und was je Dokument eingesetzt wird (Muster aus Prompt-Editoren wie Langfuse).
const MARK='rounded-sm bg-info/10 px-1 text-info';
const markiere=h=>h.replace(/‹[^›]*›/g,m=>'<span class="'+MARK+'">'+m+'</span>');
// Lesbar statt Code: Text mit Absätzen und Zeilenumbrüchen in normaler Schrift, Objekte als Tabelle.
function prosa(t){
  const abs=String(t||'').trim().split(/\n\s*\n/).map(a=>'<p>'+markiere(txt(a)).replace(/\n/g,'<br>')+'</p>').join('');
  return '<div class="grid max-h-96 gap-2 overflow-y-auto leading-relaxed">'+(abs||'<p>—</p>')+'</div>';
}
// Stücke aus classify.py: [Text, eingesetzt als …, nur wenn …]. Fester Text normal, Eingesetztes
// hinterlegt; ein Block, der nur manchmal kommt, bekommt seine Bedingung als kleine Zeile davor.
function teileHtml(T,PL){
  let aus='', w0=null;
  for(const [t,v,w] of (T||[])){
    if(w&&w!==w0) aus+='<span class="text-muted-foreground text-xs">'+txt(w)+'</span><br>';
    w0=w||null;
    const h=txt(t).replace(/\n/g,'<br>');
    if(!v){ aus+=h; continue; }
    const pl=PL&&PL[v];
    // Angehängter fester Text (etwa die Feld-Anweisung): beschriftet, aber nicht hinterlegt.
    if(!pl&&PL){ aus+='<br><span class="text-muted-foreground text-xs">'+txt(v)+'</span><br>'+h; continue; }
    // Leerer Platzhalter (etwa {TAGBLOCK} bei ausgeschaltetem Tagging): sagen, dass hier nichts kommt.
    if(!t.trim()){ aus+='<span class="text-muted-foreground text-xs">[{'+txt(v)+'} leer]</span> '; continue; }
    aus+='<span class="'+MARK+'" title="'+txt(pl?'{'+v+'} — '+pl:v)+'">'+h+'</span>';
  }
  return '<div class="max-h-96 overflow-y-auto leading-relaxed">'+(aus||'—')+'</div>';
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
// Eingabe und Ausgabe als eigene, abgesetzte Kästen mit farbigem Etikett — wie die Input-/Output-
// Bereiche in Trace-Ansichten (Langfuse, n8n), statt schlichter Aufklapp-Zeilen.
function klapp(titel,inhalt,offen){
  const m=/^(Eingabe|Ausgabe)(?: — )?(.*)$/.exec(titel), art=m?m[1]:'', rest=m?m[2]:titel;
  const etikett=art?'<span class="badge" data-variant="'+(art==='Eingabe'?'info':'success')+'">'+art+'</span>':'';
  // Die ersten drei Zeilen stehen immer da; ist mehr Text da, blendet er nach unten aus
  // (Maske statt Farbverlauf: kommt ohne Farbwert aus) und „… mehr anzeigen" klappt ihn auf.
  // Sonderweg: C22 hat weder line-clamp noch eine Ausblende-Klasse (C22-Backlog T-9).
  const klemme=offen?'':' data-klemme style="'+KLEMME+'"';
  return '<div class="min-w-0 rounded-lg border bg-background/70">'+
    '<div class="flex items-center gap-3 px-4 py-3 font-medium">'+etikett+'<span>'+txt(rest)+'</span></div>'+
    '<div class="grid min-w-0 gap-2 border-t p-4">'+
    // Klemme als Block, der Inhalt als Grid darin: Wäre die Klemme selbst ein Grid, schrumpfte ein
    // innerer Scrollbereich auf ihre Höhe — dann gäbe es nie einen Überhang zu messen.
    '<div class="min-w-0 overflow-hidden leading-relaxed"'+klemme+'><div class="grid min-w-0 gap-3">'+inhalt+'</div></div>'+
    '<button type="button" class="btn w-fit" data-variant="ghost" data-size="sm" hidden onclick="aufklemmen(this)">… mehr anzeigen</button></div></div>';
}
const KLEMME='max-height:5.6em;mask-image:linear-gradient(to bottom,black 60%,transparent)';
// Nach dem Zeichnen messen: Wo alles in drei Zeilen passt, fällt die Klemme weg (kein Ausblenden,
// kein Knopf); sonst erscheint der Knopf. Messen geht erst, wenn die Kästen im Dokument stehen.
function klemmen(wurzel){
  for(const k of wurzel.querySelectorAll('[data-klemme]')){
    const knopf=k.nextElementSibling;
    if(k.scrollHeight>k.clientHeight+2){ knopf.hidden=false; }
    else { k.removeAttribute('style'); k.removeAttribute('data-klemme'); }
  }
}
function aufklemmen(knopf){
  const k=knopf.previousElementSibling, zu=k.hasAttribute('data-klemme');
  if(zu){ k.removeAttribute('style'); k.removeAttribute('data-klemme'); knopf.textContent='weniger anzeigen'; }
  else { k.setAttribute('style',KLEMME); k.setAttribute('data-klemme',''); knopf.textContent='… mehr anzeigen'; }
}
function schritt(o){
  // Auslöser oben (jeder mit Symbol) und Ende unten (Haken oder Kreuz), mit Luft zum Rand.
  const pille=(sym,t)=>'<div class="flex items-center gap-3 rounded-full border bg-muted px-6 py-3 text-base font-semibold shadow-md">'+sym+txt(t)+'</div>';
  if(o.art==='grenze'&&o.ende) return '<div class="flex justify-center mb-6">'+pille(SYME[o.fehler?'x':'check'],o.titel)+'</div>';
  if(o.art==='grenze') return '<div class="flex flex-col items-center gap-3 pt-6"><span class="text-muted-foreground text-base">Auslöser</span>'+
    '<div class="flex flex-wrap justify-center gap-3">'+o.ausloeser.map(a=>pille(SYMA[a[0]]||'',a[1])).join('')+'</div></div>';
  const a=ART[o.art]||['',''];
  // Symbol GETRENNT vom Chip und größer — im Chip war es zu klein, um etwas zu sagen.
  const badge=(SYMG[a[2]]||'')+'<span class="badge"'+(a[1]?' data-variant="'+a[1]+'"':'')+'>'+a[0]+'</span>';
  const erg=o.ergebnis?'<span class="badge" data-variant="'+(o.variante||'outline')+'">'+txt(o.ergebnis)+'</span>':'';
  // Regeln als Tabelle „Wenn → Dann" in normaler Schrift — Plaketten mit Text waren schwer zu lesen.
  const regeln=(o.regeln||[]).length?'<div class="overflow-x-auto"><table class="table"><thead><tr><th>Wenn</th><th>Dann</th></tr></thead><tbody>'+
    o.regeln.map(r=>'<tr><td>'+txt(r[0])+'</td><td>'+r[1]+'</td></tr>').join('')+'</tbody></table></div>':'';
  const stand=(o.stand||[]).length?'<p class="text-muted-foreground text-xs">Aktuell: '+o.stand.map(x=>txt(x[0])+' <b>'+txt(x[1])+'</b>').join(' · ')+'</p>':'';
  // min-w-0: ein Grid-Kind ist sonst so breit wie sein längster Inhalt, Code liefe aus der Karte.
  const klappen=(o.klappen||[]).length?'<div class="grid min-w-0 gap-3">'+o.klappen.map(k=>klapp(k[0],k[1],k[2])).join('')+'</div>':'';
  return '<div class="card bg-muted shadow-md"'+(o.id?' id="k-'+o.id+'"':'')+'><header class="flex flex-wrap items-center justify-between gap-3">'+
    '<h3 class="flex items-center gap-3 text-sm font-semibold">'+badge+txt(o.titel)+'</h3>'+
    '<div class="flex items-center gap-2">'+erg+(o.knopf||'')+'</div></header>'+
    '<section class="grid min-w-0 gap-4">'+(o.was?'<p class="text-muted-foreground">'+o.was+'</p>':'')+(o.text?'<p>'+o.text+'</p>':'')+regeln+stand+klappen+'</section></div>';
}
// Ein Schritt ist ein Container um alles, was zu ihm gehört: aufeinanderfolgende Einträge mit
// derselben Phase werden zu einem nummerierten Schritt zusammengefasst, darin kleine Pfeile.
function kette(liste){
  const gruppen=[];
  for(const o of liste){ const g=gruppen[gruppen.length-1];
    if(o.phase&&g&&g.phase===o.phase) g.teile.push(o); else gruppen.push({phase:o.phase,teile:[o]}); }
  let n=0;
  return gruppen.map(g=>{
    if(!g.phase) return g.teile.map(schritt).join(PFEIL_K);
    return '<div class="card shadow-md"><header><h2 class="flex items-center gap-3 text-base font-semibold">'+
      '<span class="text-muted-foreground tabular-nums">'+(++n)+'</span>'+txt(g.phase)+'</h2></header>'+
      '<section class="grid min-w-0">'+g.teile.map(schritt).join(PFEIL_I)+'</section></div>';
  }).join(PFEIL_K);
}
"""


# ---------------------------------------------------------------- Aktivität
def aktivitaet() -> str:
    karten = "".join(
        f'<button type="button" class="card min-w-0 flex-1 cursor-pointer text-left hover:border-ring" data-size="sm" '
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
    lauf = dialog("lauf", "Lauf", '<div id="lauf-schritte" class="grid gap-3"></div>')
    arten_js = "{" + ",".join(f"'{a}':['{t}','{v}']" for a, t, _, v in ARTEN) + ",'trockenlauf':['Trockenlauf','outline'],'hinweis':['Hinweis','outline'],'vorschlag':['Vorschlag','outline']}"
    return (
        kopf("Aktivität", "Was der Klassifizierer getan hat. Kästen und Verlauf filtern, eine Zeile öffnet den Lauf.",
             manuell)
        + '<div id="laufend" class="mb-4"></div>'
        # Eine Reihe mit fünf: min-w-0 statt Mindestbreite (sonst bricht die fünfte um).
        + f'<div class="flex gap-4">{karten}</div>'
        + abschnitt("Verlauf (60 Tage) — Klick auf einen Tag filtert", '<div id="verlauf" class="w-full"></div>')
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
const ART_SYM={klassifiziert:'circle-check',ocr:'file-text',repariert:'refresh-ccw',fehler:'circle-alert',uebersprungen:'clock',trockenlauf:'eye',hinweis:'info'};
function badge(art){const a=ARTEN[art]||[art,'outline'];return '<span class="flex items-center gap-2">'+(SYMK[ART_SYM[art]]||'')+'<span class="badge" data-variant="'+a[1]+'">'+txt(a[0])+'</span></span>'}
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
    const hinweis = e.ocr ? 'mit OCR' : (e.art==='fehler'||e.art==='hinweis'||e.art==='ocr'||e.art==='uebersprungen' ? txt(e.text.replace(/^\S+\s+\d+:?\s*\|?\s*/,'')).slice(0,90) : '');
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
// Verlauf als flache Balkenreihe über die volle Breite. Das C22-Diagramm hat ein festes
// Seitenverhältnis (320×180): voll breit würde es riesig hoch und die Beschriftung überlappte.
// Sonderweg aus C22-Farben (bg-success/info/destructive/muted) — Diagramm mit einstellbarer
// Höhe ist im C22-Backlog gemeldet. Die Höhen sind Daten (style), keine Gestaltung.
const SERIEN=[['klassifiziert','Klassifiziert','bg-success'],['ocr','OCR','bg-info'],['fehler','Fehler','bg-destructive'],['uebersprungen','Übersprungen','bg-muted-foreground']];
async function verlauf(){
  let d; try{ d=await holen('/api/verlauf?tage=60'); }catch(e){ return; }
  const tage=d.verlauf||[], el=document.getElementById('verlauf');
  const max=Math.max(1,...tage.map(t=>SERIEN.reduce((a,[k])=>a+(t[k]||0),0)));
  const saeulen=tage.map((t,i)=>{
    // Vor der ersten Logzeile gab es keine Aufzeichnung — leerer Platz, kein Filter.
    if(t.vor_beginn) return '<span class="flex h-full flex-1" title="'+txt(t.tag+': vor Beginn der Aufzeichnung')+'"></span>';
    const teile=SERIEN.filter(([k])=>t[k]).map(([k,n,c])=>'<div class="'+c+'" style="height:'+(t[k]/max*100)+'%"></div>').join('');
    const summe=SERIEN.reduce((a,[k])=>a+(t[k]||0),0);
    const titel=t.tag+': '+(summe?SERIEN.filter(([k])=>t[k]).map(([k,n])=>n+' '+t[k]).join(', '):'nichts');
    return '<button type="button" class="flex h-full flex-1 cursor-pointer flex-col justify-end rounded-t-sm hover:bg-muted" title="'+txt(titel)+'" onclick="setzeFilter({...F,tag:\''+t.tag+'\'})">'+teile+'</button>';
  }).join('');
  const achse=tage.map((t,i)=>'<span class="flex-1 text-center text-muted-foreground text-xs">'+((i%7===0||i===tage.length-1)?t.tag.slice(8)+'.'+t.tag.slice(5,7)+'.':'')+'</span>').join('');
  const legende=SERIEN.map(([k,n,c])=>'<span class="flex items-center gap-1"><span class="size-2 rounded-sm '+c+'"></span>'+n+'</span>').join('');
  const erster=tage.find(t=>!t.vor_beginn), seit=(erster&&tage[0].vor_beginn)
    ?'<div class="mt-1 text-center text-muted-foreground text-xs">Aufzeichnung seit '+erster.tag.slice(8)+'.'+erster.tag.slice(5,7)+'.'+erster.tag.slice(0,4)+'</div>':'';
  el.innerHTML='<div class="flex h-40 w-full items-end gap-0.5 border-b">'+saeulen+'</div>'+
    '<div class="mt-1 flex w-full gap-0.5">'+achse+'</div>'+seit+
    '<div class="mt-3 flex flex-wrap justify-center gap-4 text-muted-foreground text-xs">'+legende+'</div>';
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
  const tr=t.trigger||'automatisch (Post-Consume)';
  const trSym=tr.startsWith('KI-Knopf mit')?'message-square':tr.startsWith('KI-Knopf')?'bot':tr.startsWith('Bestands')?'list':tr.startsWith('manuell')?'layout-dashboard':'file-plus';
  const L=[{art:'grenze',ausloeser:[[trSym,tr+(t.ts?' · '+t.ts:'')]]}];
  if(t.hinweis) L.push({phase:'Vorbereiten',art:'code',titel:'Hinweis vom Knopf',text:txt(t.hinweis)});
  // Nur Schritte, die in DIESEM Lauf passiert sind: was fehlt, lief nicht.
  if(o.triggered) L.push({phase:'Text beschaffen',art:'ocr',titel:'OCR — Text neu erkennen',
    ergebnis:o.triggered?(o.error?'OCR-Fehler':o.verworfen?'OCR verworfen':'OCR gelesen'):'Paperless-Text',
    variante:o.error?'destructive':o.triggered?'info':'success',
    text:txt(o.grund||'')+(o.chars?' · '+o.chars+' Zeichen':'')+(o.verworfen?' · '+txt(o.verworfen):'')+(o.error?' · '+txt(o.error):''),
    klappen:o.excerpt?[['Ausgabe — erkannter Text','<div class="grid gap-2">'+md(o.excerpt)+'</div>']]:[]});
  // Seit 2026-09-27: Vorsuche ohne KI (t.vorsuche). Ältere Läufe haben noch Pass 0 (t.pass0).
  const vs=t.vorsuche, vk=Object.entries((vs&&vs.kandidaten)||{});
  if(vs) L.push({phase:'Kandidaten suchen',art:'code',titel:'Mail, Stammdaten und Namen im Text',
    text:(vs.mail?'Mail: '+txt(vs.mail)+'<br>':'')+
      (vk.length?'Kandidaten für Pass 1: '+vk.map(([n,g])=>'<b>'+txt(n)+'</b> ('+g.map(txt).join(', ')+')').join(' · '):'Nichts gefunden — Pass 1 nennt den Absender selbst.')});
  if(t.pass0) L.push({phase:'Kandidaten suchen',art:'ki',titel:'Pass 0 — Absender erkennen (alter Lauf)',ergebnis:p0.vorschlag||'keiner',
    text:'Quelle: '+txt(p0.quelle||'—')+' · Kandidaten: '+((p0.kandidaten||[]).map(txt).join(', ')||'keine'),
    klappen:p0.system?[['Eingabe — Anweisung (System-Prompt)',prosa(p0.system)],['Eingabe — Nachricht',prosa(p0.user||'')],['Ausgabe',tabelle(p0.response||{})]]:[]});
  if(t.pass1) L.push({phase:'Analysieren',art:'ki',titel:'Pass 1 — Dokument analysieren',ergebnis:r.document_type||'kein Typ',variante:r.document_type?'success':'warning',
    text:'Korrespondent: '+txt(r.correspondent||'—')+' · Datum: '+txt(r.document_date||'—')+(r.needs_ocr?' · meldet unlesbaren Text':''),
    klappen:[['Eingabe — Anweisung (System-Prompt)',prosa(p1.system||'—')],['Eingabe — Nachricht',prosa(p1.user||'—')],['Ausgabe',tabelle(r),true]]});
  if(o.nach_pass1) L.push({phase:'Analysieren',art:'entscheidung',titel:'OCR-Nachlauf',ergebnis:o.nachlauf_fehler?'Fehler':o.nachlauf_verworfen?'verworfen':'nachgeholt',
    variante:o.nachlauf_fehler?'destructive':'info',text:txt(o.nach_pass1.join('; '))+(o.nachlauf_verworfen?' · '+txt(o.nachlauf_verworfen):'')});
  const kname=((k.ergebnis||'').match(/'([^']*)'/)||[])[1]||k.vorschlag||'—';
  const kart=(k.ergebnis||'').startsWith('NEU')?'neu angelegt':(k.ergebnis||'').startsWith('exakt')?'bekannt':(k.ergebnis||'—');
  if(t.correspondent) L.push({phase:'Korrespondent zuordnen',art:'entscheidung',titel:'Abgleich mit den Korrespondenten',
    text:'Ergebnis: <b>'+txt(kart)+'</b>'+(kname!=='—'?' — '+txt(kname):''),
    klappen:k.pass2&&k.pass2.uebersprungen?[['Pass 2 nicht gefragt — '+txt(k.pass2.uebersprungen),prosa((k.pass2.abgelehnt||[]).join('\n'))]]:
            k.pass2?[['Eingabe — Pass 2'+(k.pass2.im_gespraech?' (angehängt an die Pass-1-Unterhaltung)':''),prosa((k.pass2.system?k.pass2.system+'\n\n':'')+(k.pass2.user||''))],['Ausgabe — Pass 2',tabelle(k.pass2.response||{})]].concat((k.pass2.abgelehnt||[]).length?[['Ausgeschlossen (Namensregel)',prosa(k.pass2.abgelehnt.join('\n'))]]:[]):[]});
  const sd=t.stammdaten;
  if(sd) L.push({phase:'Schreiben',art:'code',titel:'Stammdaten nachtragen'+(sd.trocken?' (Trockenlauf — nur gezeigt)':''),
    text:sd.fehler?'Fehler: '+txt(sd.fehler):
      (Object.keys(sd.geschrieben||{}).length?'Nachgetragen: '+Object.entries(sd.geschrieben).map(([k,v])=>txt(k)+' <b>'+txt(v)+'</b>').join(' · '):'nichts nachzutragen — Felder schon gefüllt oder nichts gefunden')+
      (Object.keys(sd.verworfen||{}).length?'<br>Verworfen: '+Object.entries(sd.verworfen).map(([k,v])=>txt(k)+' ('+txt(v)+')').join(' · '):'')});
  const felder=Object.entries(w.fields_ki||{});
  if(t.writeback||t.error) L.push({phase:'Schreiben',art:'paperless',titel:t.error?'Abgebrochen':'Nach Paperless geschrieben',ergebnis:t.error?'Fehler':(t._stage||'fertig'),variante:t.error?'destructive':'success',
    text:(w.document_type?'Typ: '+txt(w.document_type)+' · ':'')+(felder.length?felder.length+' Felder':'')+((t.repair||[]).length?' · Korrekturrunden: '+t.repair.length:'')+(t.error?' · '+txt(t.error):''),
    klappen:[['Ausgabe — geschrieben',tabelle(w),true]]});
  L.push({art:'grenze',ende:true,fehler:!!t.error,titel:t.error?'Abgebrochen':'Ende'});
  ziel.innerHTML=kette(L); klemmen(ziel);
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
    "ocr": ("OCR — Text neu erkennen", [("ocr_enabled", "OCR erlaubt"), ("ocr_always", "Immer OCR (kostet)"),
                                ("ocr_model", "OCR-Modell"), ("ocr_min_len", "Mindestlänge (Zeichen)"),
                                ("ocr_regeln.min_schluesselwoerter", "Mindestens bekannte Wörter"),
                                ("ocr_regeln.max_zeichen_je_wort", "Höchstens Zeichen je echtem Wort"),
                                ("ocr_regeln.max_muell_anteil", "Höchstanteil Zeichensalat (0–1)"),
                                ("ocr_regeln.schluesselwoerter", "Bekannte Wörter")]),
    "vorsuche": ("Mail, Stammdaten und Namen im Text", [("mail_from_field", "Feld mit Absender-Mail"),
                                                 ("eigene_kennungen.ustid", "Eigene USt-IDs"),
                                                 ("eigene_kennungen.iban", "Eigene IBANs"),
                                                 ("eigene_kennungen.domains", "Eigene Mail-Domains"),
                                                 ("eigene_kennungen.email", "Eigene Mail-Adressen"),
                                                 ("eigene_kennungen.namen", "Eigene Namen"),
                                                 ("eigene_kennungen.telefon", "Eigene Telefonnummern")]),
    "abgleich": ("Abgleich mit den Korrespondenten", [("korrespondent_beispiele", "Beispielpaare für den Abgleich")]),
    "stammdaten": ("Stammdaten nachtragen", [("stammdaten_erfassen", "Stammdaten erfassen"),
                                             ("eigene_kennungen.ustid", "Eigene USt-IDs"),
                                             ("eigene_kennungen.iban", "Eigene IBANs"),
                                             ("eigene_kennungen.domains", "Eigene Mail-Domains"),
                                             ("eigene_kennungen.email", "Eigene Mail-Adressen")]),
    "pass1": ("Pass 1 — Analyse", [("system_prompt", "System-Prompt (leer = eingebaut; {TYPES}, {TAGBLOCK}/{TAGS})"),
                                   ("eigene_regel", "Regel zum Gegenüber (leer = eingebaut)"),
                                   ("model", "Modell"), ("temperature", "Temperatur"),
                                   ("content_max_len", "Text bis (Zeichen, gesamt)"),
                                   ("content_end_len", "Davon am Ende (Zeichen)")]),
    "nachlauf": ("Text lesbar laut KI?", [("ocr_regeln.nach_ki_meldung", "Wenn die KI unlesbaren Text meldet"),
                                          ("ocr_regeln.wenn_kein_typ", "Wenn kein Dokumenttyp erkannt"),
                                          ("ocr_regeln.wenn_kein_korrespondent", "Wenn kein Korrespondent erkannt")]),
    "schreiben": ("Nach Paperless schreiben", [("titel_setzen", "Titel setzen"),
                                               ("manual_fields", "Felder, die die KI nie anfasst"),
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
            + '<div id="schritte" class="grid gap-3"><p class="text-muted-foreground">lädt…</p></div>' + editor
            + "<script>" + _JS_GRUND + _JS_SCHRITTE_FERTIG + "const KNOTEN=" + knoten_js + ";" + _JS_ABLAUF + "</script>")


_JS_ABLAUF = r"""
let CFG={}, V={}, AKTIV=null;
function wert(pfad){return pfad.split('.').reduce((o,k)=>o==null?undefined:o[k],CFG)}
function an(b){return b?'an':'aus'}
function knopf(id){return '<button type="button" class="btn" data-variant="outline" data-size="sm" onclick="bearbeiten(\''+id+'\')">'+%STIFT%+'Einstellungen</button>'}
function zeichnen(){
  const o=CFG.ocr_regeln||{}, mz=o.min_zeichen??CFG.ocr_min_len;
  const L=[
    {art:'grenze',ausloeser:[['file-plus','nach dem Import (automatisch)'],['bot','KI-Knopf in Paperless'],['message-square','KI-Knopf mit Hinweis'],['layout-dashboard','Panel'],['list','Bestands-Durchlauf']]},
    {phase:'Vorbereiten',art:'paperless',titel:'Dokument laden',
      was:'Holt Titel, Text, Metadaten und Felder des Dokuments über die Paperless-API.'},
    {phase:'Vorbereiten',art:'entscheidung',id:'vorpruefung',titel:'Schon klassifiziert?',knopf:knopf('vorpruefung'),
      was:'Schutz vor doppelter Arbeit: Ein automatischer Lauf bearbeitet jedes Dokument nur einmal.',
      regeln:[['der Klassifizierer ist ausgeschaltet (automatischer Lauf)','Ende'],
              ['automatischer Lauf und das Dokument trägt den Marker-Tag','Ende — schon klassifiziert'],
              ['KI-Knopf oder Panel','immer weiter'],['sonst','weiter']],
      stand:[['Klassifizierer',an(CFG.enabled)],['Marker-Tag',CFG.marker_tag]]},
    {phase:'Text beschaffen',art:'ocr',id:'ocr',titel:'OCR — Text neu erkennen',knopf:knopf('ocr'),
      was:'Texterkennung: <b>'+txt(CFG.ocr_model)+'</b> liest das PDF neu und ersetzt den Text, den Paperless beim Import erkannt hat. '+
          'Das lohnt sich nur, wenn dieser Text schlecht ist — sonst bleibt er.',
      regeln:[['KI-Knopf in Paperless','neu erkennen'],['„Immer OCR“ ist eingeschaltet','neu erkennen'],
              ['der Text ist kürzer als '+mz+' Zeichen','neu erkennen'],
              ['weniger als '+o.min_schluesselwoerter+' bekannte Wörter im Text','neu erkennen'],
              ['mehr als '+Math.round((o.max_muell_anteil||0)*100)+' % Zeichensalat','neu erkennen'],
              ['sonst','Paperless-Text behalten']],
      stand:[['OCR erlaubt',an(CFG.ocr_enabled)],['Immer OCR',an(CFG.ocr_always)]],
      klappen:[['Eingabe — das Dokument','<p>Die PDF-Datei aus Paperless.</p>'],['Ausgabe — der erkannte Text','<p>Text als Markdown, mit Überschriften und Tabellen.</p>']]},
    {phase:'Kandidaten suchen',art:'code',id:'vorsuche',titel:'Mail, Stammdaten und Namen im Text',knopf:knopf('vorsuche'),
      was:'Ohne KI: Kam das Dokument per Mail, zählt die Absender-Mail. Außerdem sucht paperlaiss immer im Text nach den Stammdaten aller Korrespondenten (USt-ID, IBAN, Mail, Domain, Kundennummer) und im Briefkopf nach ihren Namen und Aliasen. Was gefunden wird, geht mit Kontext und Fundstelle als Kandidat an Pass 1.',
      regeln:[['die Absender-Mail passt zu genau einem Korrespondenten','starker Kandidat, keine Zuordnung (Portale!)'],
              ['die Mail kommt von einer eigenen Adresse oder Domain','Weiterleitung — zählt nicht'],
              ['Stammdaten eines Korrespondenten stehen im Text','Kandidat (stärkster Hinweis)'],
              ['alle Wörter eines Namens oder Alias stehen im Briefkopf (erste 1000 Zeichen)','Kandidat (schwächer)'],['der Name ist ein eigener Name (Firma oder Haushalt)','kein Kandidat'],
              ['eigene Kennungen im Text','zählen nie'],['nichts gefunden','Pass 1 nennt den Absender ohne Kandidaten']],
      stand:[['eigene USt-IDs',((CFG.eigene_kennungen||{}).ustid||[]).length],['eigene IBANs',((CFG.eigene_kennungen||{}).iban||[]).length],['eigene Domains',((CFG.eigene_kennungen||{}).domains||[]).length],['eigene Adressen',((CFG.eigene_kennungen||{}).email||[]).length]]},
    {phase:'Analysieren',art:'ki',id:'pass1',titel:'Pass 1 — Dokument analysieren',knopf:knopf('pass1'),
      was:'Die Hauptanfrage: Die KI liest den Text und bestimmt Dokumenttyp, Absender, Datum, Felder, Zusammenfassung und Tags. '+
          'Modell <b>'+txt(CFG.model)+'</b>, Temperatur '+txt(CFG.temperature)+', Text bis '+txt(CFG.content_max_len)+' Zeichen (bei längeren Dokumenten Anfang + die letzten '+txt(CFG.content_end_len??1000)+'). Die Antwort ist per JSON-Schema festgelegt (Dokumenttyp nur aus der Liste).',
      klappen:[['Eingabe — Anweisung (System-Prompt)',promptEditor()],
               ['Eingabe — Nachricht je Dokument',teileHtml(V.nachricht_teile)],
               ['Ausgabe',tabelle({document_type:'Dokumenttyp aus der Liste, oder leer',correspondent:'Name des Absenders, oder leer',
                  fields:'je Feld: Wert · leer (löschen) · „BEHALTEN“',document_date:'tatsächliches Dokumentdatum (JJJJ-MM-TT)',
                  summary:'kurze Zusammenfassung',titel_kennung:'was dieses Dokument unterscheidet (Nummer, Zeitraum, Betreff) — für den Titel',tags:'Tags aus der Liste (nur bei aktivem Tagging)',needs_ocr:'ja, wenn der Text unlesbar ist'},['Feld','Bedeutung'])]]},
    {phase:'Analysieren',art:'entscheidung',id:'nachlauf',titel:'Text lesbar laut KI?',knopf:knopf('nachlauf'),
      was:'Meldet die KI unlesbaren Text, wird die OCR nachgeholt und Pass 1 mit dem neuen Text wiederholt — in derselben Unterhaltung.',
      regeln:[['in diesem Lauf lief die OCR schon','weiter — kein zweites Mal'],
              ['die KI meldet unlesbaren Text','OCR nachholen, Pass 1 wiederholen'],
              ['kein Dokumenttyp erkannt','ebenso (wenn eingeschaltet)'],['kein Korrespondent erkannt','ebenso (wenn eingeschaltet)'],
              ['sonst','weiter']],
      stand:[['bei KI-Meldung',an(o.nach_ki_meldung)],['ohne Typ',an(o.wenn_kein_typ)],['ohne Korrespondent',an(o.wenn_kein_korrespondent)]]},
    {phase:'Korrespondent zuordnen',art:'entscheidung',id:'abgleich',titel:'Abgleich mit den Korrespondenten',knopf:knopf('abgleich'),
      was:'Ordnet den Absender aus Pass 1 einem Korrespondenten in Paperless zu — oder legt einen neuen an.',
      regeln:[['der Name aus Pass 1 passt exakt zu einem Korrespondenten','zuordnen'],
              ['ähnliche Korrespondenten, die die Namensregel bestehen','Pass 2: die KI wählt einen davon oder keinen'],
              ['kein ähnlicher Name besteht die Namensregel','ohne zweiten KI-Aufruf neu anlegen'],
              ['Namensregel','Name steckt im anderen (Tippfehler nur bei langen Wörtern) · Personen: Nach- und Vorname gleich · sonst ein seltenes gemeinsames Wort ab 6 Zeichen']],
      klappen:[['Eingabe — Pass 2 (eine weitere Nachricht in der Pass-1-Unterhaltung)',prosa(V.pass2_frage||'')],
               ['Ausgabe — Pass 2',tabelle({match:'exakter Name aus der Liste, oder leer'},['Feld','Bedeutung'])]]},
    {phase:'Schreiben',art:'code',id:'stammdaten',titel:'Stammdaten nachtragen',knopf:knopf('stammdaten'),
      was:'Trägt USt-ID, IBAN, Mail, Domain, Telefon, Adresse und Kundennummer des Absenders beim zugeordneten Korrespondenten nach — aus der Absender-Mail und dem, was Pass 1 unter „absender“ liefert. Im Korrespondenten-Dialog in Paperless steht dann, woher der Wert kommt.',
      regeln:[['das Feld ist leer','füllen'],
              ['Listenfeld (IBAN, Mail, Domain, Telefon, Kundennummer), Korrespondent exakt zugeordnet','neuen Wert anhängen (höchstens 10)'],
              ['Zuordnung nur über Pass 2 (ähnlicher Name)','nichts anhängen, nur leere Felder füllen'],
              ['USt-ID oder Adresse schon gefüllt','bleibt — nie überschreiben; eine andere USt-ID wird als Warnung gemeldet'],
              ['der Wert gehört schon einem anderen Korrespondenten','verworfen'],['der Wert ist eine eigene Kennung','verworfen'],
              ['USt-ID, IBAN oder Mail hat kein gültiges Format','verworfen'],['Freemail-Adresse (gmail, gmx …)','nur die Adresse, keine Domain'],
              ['die Absender-Mail gehört nicht erkennbar zu diesem Absender (z. B. ein Portal)','Mail und Domain nicht übernehmen'],
              ['die Zuordnung ist unsicher (bestehender behalten)','nichts nachtragen'],['sonst','nachtragen, mit Herkunft']],
      stand:[['Stammdaten erfassen',an(CFG.stammdaten_erfassen!==false)]]},
    {phase:'Schreiben',art:'paperless',id:'schreiben',titel:'Nach Paperless schreiben',knopf:knopf('schreiben'),
      was:'Schreibt das Ergebnis über die API zurück nach Paperless. Lehnt Paperless einen Wert ab, geht die Fehlermeldung in dieselbe KI-Unterhaltung; die KI korrigiert, dann wird erneut geschrieben.',
      text:(CFG.titel_setzen!==false?'Titel („Korrespondent – Dokumentart Kennung“), ':'')+'Typ, Korrespondent, Datum, Felder'+(CFG.tagging_enabled?', Tags':'')+'; Tag „'+txt(CFG.marker_tag)+'“. Nie angefasst: '+((CFG.manual_fields||[]).map(txt).join(', ')||'—')+'.'},
    {phase:'Schreiben',art:'code',id:'nachbearbeitung',titel:'Eigenes Skript danach (optional)',knopf:knopf('nachbearbeitung'),
      was:'Optional: Ein eigenes Skript bekommt das Ergebnis, etwa für eine Verknüpfung in ein anderes System.',
      text:CFG.nachbearbeitung?'Eingerichtet: <b>'+txt(CFG.nachbearbeitung)+'</b>':'Nicht eingerichtet.'},
    {art:'grenze',ende:true,titel:'Ende'}];
  const sch=document.getElementById('schritte'); sch.innerHTML=kette(L); klemmen(sch);
}
async function laden(){
  try{ CFG=await holen('/api/config'); }catch(e){}
  try{ V=await holen('/api/prompt-vorschau'); }catch(e){ V={system:'Vorschau nicht verfügbar: '+e.message}; }
  zeichnen();
}
// Ein Feld statt zwei: die Anweisung so, wie sie an die KI geht, eingesetzte Werte hinterlegt.
// „Bearbeiten“ zeigt die Vorlage darüber; jede Änderung rechnet classify.py sofort neu durch.
function promptEditor(){
  const pl=Object.entries(V.platzhalter||{}).map(([k,b])=>'<span class="'+MARK+'">{'+txt(k)+'}</span> '+txt(b)).join(' · ');
  return '<div class="flex flex-wrap items-center gap-2"><span class="text-muted-foreground text-xs">'+
      (V.eigener_prompt?'Eigener Prompt.':'Eingebauter Prompt.')+' Hinterlegt = wird beim Senden eingesetzt.</span>'+
      '<button type="button" id="p-auf" class="btn ms-auto" data-variant="outline" data-size="sm" onclick="promptAuf()">'+%STIFT%+'Bearbeiten</button></div>'+
    '<div id="p-editor" class="grid gap-2" hidden>'+
      '<textarea class="textarea max-h-96 w-full font-mono" rows="14" id="prompt-vorlage" oninput="promptLive()"></textarea>'+
      '<p class="text-muted-foreground text-xs">Platzhalter: '+pl+'</p>'+
      '<div class="flex flex-wrap items-center gap-2"><button type="button" class="btn" data-size="sm" onclick="promptSpeichern()">Speichern</button>'+
      '<button type="button" class="btn" data-variant="outline" data-size="sm" onclick="promptZu()">Verwerfen</button>'+
      '<button type="button" class="btn" data-variant="ghost" data-size="sm" onclick="promptStandard()">Eingebauten Prompt einsetzen</button>'+
      '<span id="prompt-meldung" class="text-muted-foreground text-sm"></span></div></div>'+
    '<p class="text-muted-foreground text-xs" id="p-titel" hidden>Vorschau — so geht die Anweisung an die KI:</p>'+
    '<div id="p-vorschau">'+teileHtml(V.system_teile,V.platzhalter)+'</div>';
}
function promptAuf(){
  const t=document.getElementById('prompt-vorlage'), k=t.closest('[data-klemme]');
  if(k) aufklemmen(k.nextElementSibling);
  t.value=V.vorlage||'';
  document.getElementById('p-editor').hidden=false; document.getElementById('p-titel').hidden=false;
  document.getElementById('p-auf').hidden=true; t.focus();
}
function promptZu(){ zeichnen(); }
function promptStandard(){ const t=document.getElementById('prompt-vorlage'); t.value=V.standard||''; promptLive(); }
let LIVE=null, LIVE_NR=0;
function promptLive(){
  clearTimeout(LIVE); const m=document.getElementById('prompt-meldung'); m.textContent='Vorschau wird gerechnet…';
  LIVE=setTimeout(async()=>{ const nr=++LIVE_NR;
    try{ const r=await senden('/api/prompt-vorschau',{system_prompt:document.getElementById('prompt-vorlage').value});
      if(nr!==LIVE_NR) return;   // eine spätere Eingabe hat schon neu gerechnet
      document.getElementById('p-vorschau').innerHTML=teileHtml(r.system_teile,r.platzhalter); m.textContent='';
    }catch(e){ m.textContent='Vorschau fehlgeschlagen: '+e.message; } },500);
}
async function promptSpeichern(){
  const m=document.getElementById('prompt-meldung');
  let wert=document.getElementById('prompt-vorlage').value;
  if(wert.trim()===(V.standard||'').trim()) wert='';   // unverändert = eingebauter Prompt, keine Kopie ablegen
  try{ const d=await senden('/api/config',{system_prompt:wert});
    m.textContent=(d.uebergangen||[]).length?'übergangen: '+d.uebergangen.join(', '):'gespeichert'; await laden();
  }catch(e){ m.textContent='Fehler: '+e.message; }
}
function feldHtml(pfad,name){
  const v=wert(pfad), id='f-'+pfad.replace(/\W/g,'_');
  if(typeof v==='boolean') return '<div class="field" role="group" data-orientation="horizontal"><input class="input" type="checkbox" role="switch" id="'+id+'"'+(v?' checked':'')+'><label class="label" for="'+id+'">'+txt(name)+'</label></div>';
  let e;
  if(pfad==='system_prompt') e='<textarea class="textarea max-h-96 font-mono" rows="18" id="'+id+'">'+txt(v)+'</textarea>';
  else if(pfad==='eigene_regel') e='<textarea class="textarea max-h-48 font-mono" rows="6" id="'+id+'">'+txt(v??'')+'</textarea>';
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
            + '<div>'
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
    "model": ("KI-Modell & Prompt", "Modell", "Mistral-Modell für die Analyse (Pass 1 und 2)."),
    "temperature": ("KI-Modell & Prompt", "Temperatur",
                    "Wie frei das Modell antwortet: 0 = immer gleich, höher = kreativer. Für Klassifizierung niedrig halten (0–0,2)."),
    "content_max_len": ("KI-Modell & Prompt", "Text bis (Zeichen, gesamt)",
                        "So viel vom Dokumenttext geht an die KI — bei längeren Dokumenten der Anfang plus das Ende "
                        "(siehe unten). Mehr kostet mehr und ist selten nötig."),
    "content_end_len": ("KI-Modell & Prompt", "Davon am Ende (Zeichen)",
                        "Ist ein Dokument länger als die Gesamtlänge, bekommt die KI den Anfang und diese Zahl "
                        "Zeichen vom Ende — dort stehen oft Summe, Fälligkeit und Bankverbindung."),
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
    "leerseiten_entfernen": ("Allgemein", "Leere Seiten entfernen",
                             "An: beim Import fallen komplett weiße Seiten aus einem PDF (nur Staub unter 1 mm zählt als "
                             "weiß; Seitenzahl, Nummer oder Strich bleiben). Nie bei signierten, verschlüsselten PDFs, "
                             "E-Rechnungen oder wenn alle Seiten leer wären. Wirkt über das Pre-Consume-Skript vorab.py."),
    "titel_setzen": ("Allgemein", "Titel setzen",
                     "An: der Titel wird „Korrespondent – Dokumentart Kennung“, z. B. „Beispiel GmbH – Rechnung 12/2026“; "
                     "die Kennung (Nummer, Zeitraum, Betreff) bestimmt die KI. Überschrieben wie der Dokumenttyp: beim Import, "
                     "beim KI-Knopf und im Panel, nie beim Bestands-Durchlauf."),
    "summary_field": ("Felder", "Feld für die Zusammenfassung",
                      "Name eines Custom Fields (Langtext), in das die KI eine kurze Zusammenfassung schreibt. Leer = keine."),
    "mail_context_field": ("Felder", "Feld mit Mail-Kontext",
                           "Custom Field mit dem Anschreiben einer Mail; geht als Kontext an die KI. Leer = aus."),
    "mail_from_field": ("Felder", "Feld mit Absender-Mail",
                        "Custom Field mit der Absenderadresse; hilft, den Korrespondenten über die Domain zu finden. Leer = aus."),
    "korrespondent_beispiele": ("Korrespondenten", "Beispielpaare für den Abgleich",
                                "Paare [\"falsch geschrieben\", \"richtiger Name\"] — helfen der KI bei OCR-Fehlern im Absender."),
    "stammdaten_erfassen": ("Korrespondenten", "Stammdaten erfassen",
                            "An: USt-ID, IBAN, Mail, Telefon, Adresse und Kundennummer des Absenders werden beim "
                            "zugeordneten Korrespondenten nachgetragen — nur in leere Felder, nie überschreibend."),
    "eigene_kennungen.ustid": ("Korrespondenten", "Eigene USt-IDs",
                               "Eigene USt-IDs. Stehen auf fast jedem Dokument und zählen nie als Absender. Eine je Zeile."),
    "eigene_kennungen.iban": ("Korrespondenten", "Eigene IBANs",
                              "Eigene IBANs (etwa bei Lastschriften). Zählen nie als Absender. Eine je Zeile."),
    "eigene_kennungen.domains": ("Korrespondenten", "Eigene Mail-Domains",
                                 "Mail von hier ist eine Weiterleitung und ordnet nichts zu; nie als Absender erfasst. Eine je Zeile."),
    "eigene_kennungen.namen": ("Korrespondenten", "Eigene Namen",
                               "Firma oder Personen des Haushalts. Stehen im Empfängerblock jedes Dokuments. Korrespondenten mit "
                               "diesem Namen sind bei der Namenssuche keine Kandidaten, und Pass 1 erfährt, wer „wir“ sind — "
                               "gesucht ist immer das Gegenüber. Einer je Zeile."),
    "eigene_regel": ("Korrespondenten", "Regel zum Gegenüber",
                     "Wie Pass 1 den Korrespondenten wählt, wenn eigene Namen gesetzt sind (der Satz nach „… das sind WIR.“). "
                     "Leer = eingebaute Regel für eine Firma (Kunden, Ausgangsrechnung, Lohnabrechnung). {ERSTER} = erster "
                     "eigener Name. Ein Haushalt nennt hier seine eigenen Fälle (eigener Brief, Lebenslauf, Vollmacht)."),
    "eigene_kennungen.telefon": ("Korrespondenten", "Eigene Telefonnummern",
                                 "Stehen auf Dokumenten an uns und zählen nie als Absender (Suche, Erfassung). Eine je Zeile."),
    "eigene_kennungen.email": ("Korrespondenten", "Eigene Mail-Adressen",
                               "Wie die Domains, aber als volle Adresse — für eine eigene Freemail-Adresse (gmail, gmx …), "
                               "deren Domain man nicht sperren kann. Eine je Zeile."),
    "nachbearbeitung": ("Erweitert", "Eigenes Skript danach",
                        "Pfad zu einem Skript, das nach dem Schreiben läuft — für alles, was nur diese Installation braucht. Leer = aus."),
}


def einstellungen() -> str:
    import json
    return (kopf("Einstellungen", "Alle Werte der Konfiguration. Schlüssel (API-Keys) gehören in die Umgebung, nicht hierher.",
                 '<span id="meld" class="text-muted-foreground text-sm"></span>'
                 '<button type="button" class="btn" onclick="sichern()">'
                 f'{symbol("save")}Speichern</button>')
            + '<div id="felder" class="grid gap-6"><p class="text-muted-foreground">lädt…</p></div>'
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
  else if(pfad==='eigene_regel') e='<textarea class="textarea max-h-48 font-mono" rows="5" id="'+id+'">'+txt(v??'')+'</textarea>';
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
                       .replace("%CHEVK%", _json(symbol("chevron-down", "size-4 shrink-0 text-muted-foreground")))
                       .replace("%PFEILK%", _json('<div class="flex justify-center py-3 text-muted-foreground">'
                                                  + symbol("arrow-down", "size-14") + "</div>"))
                       .replace("%PFEILI%", _json('<div class="flex justify-center py-2 text-muted-foreground">'
                                                  + symbol("arrow-down", "size-8") + "</div>"))
                       .replace("%SYMG%", _json({n: symbol(n, "size-6 shrink-0 text-muted-foreground")
                                                 for n in ("inbox", "settings-2", "bot", "file-text", "git-branch",
                                                           "file-plus", "message-square", "layout-dashboard", "list")}))
                       .replace("%SYMA%", _json({n: symbol(n, "size-7 shrink-0 text-muted-foreground")
                                                 for n in ("bot", "file-plus", "message-square", "layout-dashboard", "list")}))
                       .replace("%SYME%", _json({"check": symbol("circle-check", "size-7 shrink-0 text-success"),
                                                 "x": symbol("x", "size-7 shrink-0 text-destructive")}))
                       .replace("%SYMK%", _json({n: symbol(n, "size-5 shrink-0 text-muted-foreground") for n in
                                                 ("circle-check", "file-text", "refresh-ccw", "circle-alert", "clock", "eye", "info")}))
                       .replace("%SYM%", _json({n: symbol(n) for n in ("inbox", "settings-2", "bot", "file-text", "git-branch",
                                                                       "circle-check", "refresh-ccw", "circle-alert", "clock",
                                                                       "eye", "info")})))
_JS_ABLAUF = _JS_ABLAUF.replace("%STIFT%", _json(symbol("pencil")))
