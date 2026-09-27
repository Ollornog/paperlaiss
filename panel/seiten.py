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
    "nachbearbeitung": ("Nachbearbeitung", [("nachbearbeitung", "Skript-Pfad")]),
}


def _bearbeiten(kid: str) -> str:
    if kid not in KNOTEN_FELDER:
        return ""
    return (f'<button type="button" class="btn" data-variant="outline" data-size="sm" '
            f'onclick="event.stopPropagation();bearbeiten(\'{kid}\')">{symbol("pencil")}Einstellungen</button>')


def _werte(kid: str) -> str:
    return f'<p class="text-muted-foreground text-xs" id="wert-{kid}"></p>' if kid in KNOTEN_FELDER else ""


def _klick(kid: str) -> str:
    return (f' id="k-{kid}" onclick="bearbeiten(\'{kid}\')"' if kid in KNOTEN_FELDER else "")


def _oval(text: str) -> str:
    return (f'<div class="mx-auto w-fit rounded-full border bg-muted/40 px-6 py-2 text-center text-sm font-medium">'
            f'{text}</div>')


def _pfeil(beschriftung: str = "") -> str:
    b = f'<span class="badge" data-variant="success">{beschriftung}</span>' if beschriftung else ""
    return (f'<div class="flex items-center justify-center gap-2 text-muted-foreground">'
            f'{symbol("arrow-down", "size-10")}{b}</div>')


def _schritt(kid: str, titel: str, text: str) -> str:
    return (f'<div class="card cursor-pointer hover:border-ring" data-size="sm"{_klick(kid)}>'
            f'<header class="flex flex-wrap items-center justify-between gap-2"><h2 class="flex items-center gap-2">'
            f'<span class="badge" data-variant="secondary">Schritt</span>{titel}</h2>{_bearbeiten(kid)}</header>'
            f'<section class="text-sm">{text}{_werte(kid)}</section></div>')


def _daten(kid: str, titel: str, text: str) -> str:
    return (f'<div class="card cursor-pointer bg-info/10 hover:border-ring" data-size="sm"{_klick(kid)}>'
            f'<header class="flex flex-wrap items-center justify-between gap-2"><h2 class="flex items-center gap-2">'
            f'<span class="badge" data-variant="info">Paperless</span>{titel}</h2>{_bearbeiten(kid)}</header>'
            f'<section class="text-sm">{text}{_werte(kid)}</section></div>')


def _raute(kid: str, frage: str, seitentext: str, seite: str = "nein", weiter: str = "ja") -> str:
    """Entscheidung: Raute mit der Frage, darunter der Seitenzweig; der andere Zweig geht weiter."""
    return (f'<div class="grid gap-2"{_klick(kid)}>'
            f'<div class="relative mx-auto h-36 w-80 cursor-pointer">'
            f'<svg class="absolute inset-0 size-full" viewBox="0 0 320 144" aria-hidden="true">'
            f'<polygon points="160,2 318,72 160,142 2,72" fill="var(--card)" stroke="var(--border)" stroke-width="2"/></svg>'
            f'<div class="absolute inset-0 flex items-center justify-center">'
            f'<p class="w-48 text-center text-sm font-medium leading-tight">{frage}</p></div></div>'
            f'<div class="mx-auto flex max-w-2xl items-start gap-3 rounded-md border border-dashed p-3">'
            f'<span class="badge" data-variant="warning">{seite}</span><p class="text-sm">{seitentext}</p></div>'
            f'<div class="flex justify-center">{_bearbeiten(kid)}</div>{_werte(kid)}</div>'
            + _pfeil(weiter))


def _ki(kid: str, titel: str, eingabe: str, ausgabe: str) -> str:
    return (f'<div class="card cursor-pointer border-primary hover:border-ring" data-size="sm"{_klick(kid)}>'
            f'<header class="flex flex-wrap items-center justify-between gap-2"><h2 class="flex items-center gap-2">'
            f'<span class="badge">KI</span>{titel}</h2>{_bearbeiten(kid)}</header>'
            f'<section class="grid gap-3 text-sm">'
            f'<div><p class="text-muted-foreground text-xs uppercase tracking-wide">Eingabe</p>{eingabe}</div>'
            f'<div><p class="text-muted-foreground text-xs uppercase tracking-wide">Modell</p>'
            f'<p id="modell-{kid}">…</p></div>'
            f'<div><p class="text-muted-foreground text-xs uppercase tracking-wide">Ausgabe</p>{ausgabe}</div>'
            f'{_werte(kid)}</section></div>')


def _legende() -> str:
    raute = ('<svg class="size-5" viewBox="0 0 20 20" aria-hidden="true"><polygon points="10,1 19,10 10,19 1,10" '
             'fill="var(--card)" stroke="var(--muted-foreground)" stroke-width="1.5"/></svg>')
    return ('<div class="mb-6 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">'
            '<span class="flex items-center gap-2"><span class="rounded-full border px-3 py-0.5">…</span>Start / Ende</span>'
            '<span class="flex items-center gap-2"><span class="badge" data-variant="secondary">Schritt</span>Code</span>'
            '<span class="flex items-center gap-2"><span class="badge" data-variant="info">Paperless</span>lesen / schreiben</span>'
            f'<span class="flex items-center gap-2">{raute}Entscheidung</span>'
            '<span class="flex items-center gap-2"><span class="badge">KI</span>Modell: Eingabe → Ausgabe</span></div>')


def _schluessel(*namen: str) -> str:
    return '<div class="mt-1 flex flex-wrap gap-1">' + "".join(
        f'<span class="badge" data-variant="outline">{n}</span>' for n in namen) + "</div>"


def ablauf() -> str:
    import json
    fluss = "".join([
        _oval("Dokument kommt an — nach dem Import · KI-Knopf · OCR-Knopf · Panel"), _pfeil(),
        _daten("laden", "Dokument laden", "Text, Titel, Metadaten und Felder aus Paperless."), _pfeil(),
        _raute("vorpruefung", "Automatischer Lauf und schon klassifiziert (Marker-Tag)?",
               "Ende — überspringen. Knöpfe und Panel klassifizieren immer.", seite="ja", weiter="nein"),
        _raute("ocr", "Text brauchbar?",
               "Mistral-OCR liest das Dokument neu. Beim KI- und OCR-Knopf immer. "
                   "Danach weiter — beim OCR-Knopf ist hier Schluss: nur der Text wird geschrieben."),
        _ki("pass0", "Pass 0 — Absender erkennen",
            '<p>Titel und Textanfang</p>',
            _schluessel("Absender") + '<p class="mt-1">danach Namensabgleich gegen alle Korrespondenten → Kandidaten</p>'),
        _pfeil(),
        _ki("pass1", "Pass 1 — Analyse",
            # Nur lesend in einem Textfeld: bricht um (ein Code-Block tut das nicht und liefe aus der Karte).
            '<p>System-Prompt:</p><textarea class="textarea max-h-96 w-full font-mono" rows="10" readonly '
            'id="prompt-vorschau" onclick="event.stopPropagation()">lädt…</textarea>'
            '<p class="mt-1">Nachricht: Hinweis vom Knopf · Kandidaten · Metadaten · Felder · Text</p>',
            _schluessel("document_type", "correspondent", "fields", "document_date", "summary", "tags",
                        "needs_ocr")),
        _pfeil(),
        _raute("nachlauf", "Text lesbar laut KI?",
               "OCR nachholen und Pass 1 wiederholen — nur wenn vorher noch kein OCR lief."),
        _raute("korrespondent", "Korrespondent bekannt?",
               "KI-Rückfrage mit ähnlichen Namen (Pass 2); passt keiner, wird er neu angelegt."),
        _daten("schreiben", "Nach Paperless schreiben",
               "Typ, Korrespondent, Datum, Felder. Lehnt Paperless einen Wert ab, korrigiert die KI in derselben Unterhaltung."),
        _pfeil(),
        _schritt("nachbearbeitung", "Nachbearbeitung",
                 "Optionales Skript — für alles, was nur diese Installation braucht."),
        _pfeil(), _oval("Fertig"),
    ])
    editor = dialog("knoten", "Knoten bearbeiten", '<div id="knoten-felder" class="grid gap-4"></div>',
                    fuss=('<span id="knoten-meldung" class="text-muted-foreground text-sm"></span>'
                          '<button type="button" class="btn" data-variant="outline" onclick="this.closest(\'dialog\').close()">Abbrechen</button>'
                          '<button type="button" class="btn" onclick="speichern()">Speichern</button>'))
    knoten_js = json.dumps({k: {"titel": t, "felder": f} for k, (t, f) in KNOTEN_FELDER.items()}, ensure_ascii=False)
    return (kopf("Ablauf & Prompt",
                 "So läuft ein Dokument durch paperlaiss. Knoten mit Einstellungen öffnen sie per Klick.")
            + _legende() + f'<div class="mx-auto grid max-w-3xl gap-2">{fluss}</div>' + editor
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
    // Modell, Temperatur und Textlänge stehen im KI-Knoten schon unter „Modell".
    el.innerHTML=k.felder.filter(([p])=>!['system_prompt','model','temperature','content_max_len'].includes(p)).map(([p,n])=>txt(n)+': <b>'+txt(kurz(wert(p)))+'</b>').join(' · ');
  }
}
async function laden(){
  try{ CFG=await holen('/api/config'); zeigeWerte(); }catch(e){}
  try{ const v=await holen('/api/prompt-vorschau'); document.getElementById('prompt-vorschau').value=v.system||'';
    const e=v.einstellungen||{};
    document.getElementById('modell-pass0').textContent=(e.model||'')+' — kurzer Aufruf';
    document.getElementById('modell-pass1').textContent=(e.model||'')+' · Temperatur '+(e.temperature??'')+' · Text bis '+(e.content_max_len||'')+' Zeichen';
  }catch(e){ document.getElementById('prompt-vorschau').value='Vorschau nicht verfügbar: '+e.message; }
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
# Jede Einstellung mit Gruppe, Titel und Beschreibung. Schlüssel, die hier fehlen, erscheinen
# unter „Weitere" mit ihrem rohen Namen — so geht ein neuer Schlüssel nicht verloren, fällt aber
# auf. Verschachtelte Werte (ocr_regeln.x) werden einzeln gezeigt.
GRUPPEN = ["Allgemein", "KI-Modell & Prompt", "OCR", "Tags", "Felder", "Korrespondenten", "Erweitert"]
EINSTELLUNGEN = {
    "enabled": ("Allgemein", "Klassifizierer aktiv",
                "Hauptschalter. Aus: automatisch importierte Dokumente werden übersprungen. "
                "Die KI-/OCR-Knöpfe in Paperless und das Panel funktionieren weiter."),
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
    "ocr_enabled": ("OCR", "OCR erlaubt", "Aus: paperlaiss liest nie per Mistral-OCR, auch nicht beim OCR-Knopf."),
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
    "nachbearbeitung": ("Erweitert", "Nachbearbeitung (Skript)",
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
