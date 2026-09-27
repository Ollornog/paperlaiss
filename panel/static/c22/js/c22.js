// C22 — eigenes, minimales Verhalten für Components, die Basecoat NICHT mitbringt.
// Ergänzt basecoat.all.min.js (das die übrigen Components live macht). Kein Build-Schritt,
// keine Abhängigkeit: eine Datei einbinden, fertig. Alles hängt an data-Attributen im Markup.
(function () {
  'use strict';

  // ---- Phosphor-Icons (zweite Icon-Bibliothek neben den Lucide-Inline-SVGs) --
  // Subset in icons.js (window.C22_ICONS = {name: {gewicht: "<path …>"}}), MUSS vor c22.js
  // eingebunden sein. Deklarativ: <span data-icon-ph="name" data-weight="thin|light|regular|
  // bold|fill|duotone" class="size-4">, befüllt von init()/wirePhIcons(). Programmatisch:
  // window.C22.phIcon(name, weight) -> SVG-String. Unbekannter Name/Gewicht: console.warn + leer,
  // damit ein Tippfehler nicht die ganze Seite zerlegt.
  var PH_WEIGHTS = ['thin', 'light', 'regular', 'bold', 'fill', 'duotone'];
  function phIcon(name, weight) {
    var set = window.C22_ICONS && window.C22_ICONS[name];
    if (!set) { console.warn('C22.phIcon: unbekanntes Icon "' + name + '"'); return ''; }
    var w = PH_WEIGHTS.indexOf(weight) >= 0 ? weight : 'regular';
    var inner = set[w] || set.regular;
    if (!inner) { console.warn('C22.phIcon: unbekanntes Gewicht "' + weight + '" bei "' + name + '"'); return ''; }
    return '<svg viewBox="0 0 256 256" fill="currentColor" aria-hidden="true">' + inner + '</svg>';
  }
  function wirePhIcons(root) {
    (root || document).querySelectorAll('[data-icon-ph]').forEach(function (el) {
      el.innerHTML = phIcon(el.dataset.iconPh, el.dataset.weight);
    });
  }

  // ---- Context-Menu (Basecoat hat kein Rechtsklick-JS) ---------------------
  // Markup:  <div class="context-menu" data-close="leave|leave-delay|manual">
  //            <div … oncontextmenu-Ziel …>Rechtsklick-Fläche</div>
  //            <div data-cm-panel role="menu" hidden> … Einträge … </div>
  //          </div>
  // Default (ohne data-close) ist 'manual': offen bis Klick/Rechtsklick woanders, Escape
  // oder Scroll — wie native Kontextmenüs (PO). leave/leave-delay sind explizite Varianten.
  // Untermenüs (verschachtelte [data-cm-panel]) laufen weiter rein über CSS-Hover.
  var CLOSE_DELAY = 500; // ms für data-close="leave-delay" ("kurze Verzögerung")
  var MARGIN = 8;        // Mindestabstand zum Fensterrand
  var HIT_SLOP = 24;     // Toleranzsaum ums Panel, der noch als "auf dem Menü" zählt

  // Registry aller verdrahteten Wurzelmenüs; `active` ist das gerade offene (max. eines, weil
  // jeder Rechtsklick zuerst alle schließt). Ein Ereignis (Rechtsklick woanders, Scroll, Escape,
  // Zeiger verlässt das Panel) kann so ALLE bzw. das aktive schließen.
  var registry = [];
  var active = null;
  function closeAll() { registry.forEach(function (m) { m.close(); }); }

  // Panel ist position:fixed -> Koordinaten sind Viewport-Koordinaten. Es zählt allein das
  // Fenster, nicht der Container: standardmäßig rechts/unter dem Zeiger, sonst nach links bzw.
  // über den Zeiger gekippt, damit es nie aus dem Fenster ragt.
  function positionPanel(panel, ev) {
    panel.hidden = false;               // erst sichtbar, dann messbar
    var pw = panel.offsetWidth, ph = panel.offsetHeight;
    var vw = window.innerWidth;         // echte Fenstergröße — nur sie zählt, nicht der Container
    var vh = window.innerHeight;
    var x = ev.clientX, y = ev.clientY;
    if (x + pw > vw - MARGIN) x = x - pw;                       // rechts kein Platz -> nach links
    if (y + ph > vh - MARGIN) y = y - ph;                       // unten kein Platz -> nach oben
    panel.style.left = Math.min(Math.max(MARGIN, x), vw - pw - MARGIN) + 'px';
    panel.style.top = Math.min(Math.max(MARGIN, y), vh - ph - MARGIN) + 'px';
  }

  function wireContextMenu(menu) {
    if (menu.dataset.c22Wired) return;  // idempotent (mehrfaches Init schadet nicht)
    menu.dataset.c22Wired = '1';
    var panel = menu.querySelector(':scope > [data-cm-panel]');
    if (!panel) return;
    var trigger = panel.previousElementSibling;
    // Default 'manual' (PO): das Menü bleibt offen, bis woanders geklickt/rechtsgeklickt wird
    // (oder Escape/Scroll) — wie native Kontextmenüs. Auto-Schließen beim Verlassen nur noch
    // explizit per data-close="leave"/"leave-delay".
    var obj = { panel: panel, mode: menu.dataset.close || 'manual', timer: null, close: null };

    // Klick-Untermenüs (STANDARD): verschachtelte Panels, die im Markup `hidden` tragen, werden
    // per Klick auf ihren aria-haspopup-Eintrag geöffnet/geschlossen (activateItem). Die
    // Hover-Variante (CSS group-hover, ohne hidden) bleibt unberührt.
    panel.querySelectorAll('[data-cm-panel][hidden]').forEach(function (p) { p.dataset.c22Sub = '1'; });

    function close() {
      clearTimeout(obj.timer); obj.timer = null; panel.hidden = true;
      // Untermenüs zurücksetzen, damit das Menü beim nächsten Öffnen zugeklappt startet.
      panel.querySelectorAll('[data-cm-panel]').forEach(function (p) { if (p.dataset.c22Sub) p.hidden = true; });
      panel.querySelectorAll('[aria-haspopup][aria-expanded="true"]').forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
      if (active === obj) active = null;
    }
    function open(ev) { ev.preventDefault(); clearTimeout(obj.timer); obj.timer = null; positionPanel(panel, ev); active = obj; }
    obj.close = close;
    registry.push(obj);

    if (trigger) trigger.addEventListener('contextmenu', open);

    // Links- UND Rechtsklick auf einen Eintrag verhalten sich gleich (wie native Kontextmenüs).
    panel.addEventListener('click', function (e) { activateItem(e.target, close); });
  }

  // Einen Eintrag "aktivieren" — geteilt von Links- und Rechtsklick: Checkbox/Radio togglen und
  // offen bleiben; ein echter Eintrag schließt; ein Untermenü-Öffner (aria-haspopup) togglet
  // sein Klick-Untermenü (Standard) bzw. macht bei der Hover-Variante nichts.
  function activateItem(target, close) {
    var cb = target.closest('[role=menuitemcheckbox]');
    if (cb) { cb.setAttribute('aria-checked', cb.getAttribute('aria-checked') !== 'true'); return; }
    var rd = target.closest('[role=menuitemradio]');
    if (rd) {
      rd.closest('[role=group]').querySelectorAll('[role=menuitemradio]')
        .forEach(function (el) { el.setAttribute('aria-checked', el === rd ? 'true' : 'false'); });
      return;
    }
    var opener = target.closest('[role=menuitem][aria-haspopup]');
    if (opener) {
      var sub = opener.parentElement && opener.parentElement.querySelector(':scope > [data-cm-panel]');
      if (sub && sub.dataset.c22Sub) {
        var show = sub.hidden;
        // Geschwister-Untermenüs im selben Panel schließen (max. eines offen).
        var host = opener.closest('[data-cm-panel]');
        if (host) host.querySelectorAll('[data-cm-panel]').forEach(function (p) {
          if (p.dataset.c22Sub && p !== sub) p.hidden = true;
        });
        sub.hidden = !show;
        opener.setAttribute('aria-expanded', show ? 'true' : 'false');
      }
      return; // ein Untermenü-Öffner schließt das Menü nie
    }
    if (target.closest('[role=menuitem]')) close();
  }

  // Globale Schließ-Auslöser — einmal fürs ganze Dokument, wirken auf ALLE Menüs.
  var globalsWired = false;
  function wireGlobals() {
    if (globalsWired) return;
    globalsWired = true;
    // Linksklick außerhalb eines Panels schließt alles (ein Rechtsklick feuert KEIN click-Event).
    document.addEventListener('click', function (e) {
      if (!e.target.closest('[data-cm-panel]')) closeAll();
    });
    // Rechtsklick INS offene Menü = normaler Klick auf den Eintrag (wie native Kontextmenüs),
    // ohne natives Browsermenü. Sonst: Rechtsklick woanders schließt zuerst alle (capture, also
    // VOR dem Auslöser); liegt er auf einer Auslöserfläche, öffnet deren Handler danach sein
    // eigenes — so bleibt nie mehr als ein Menü offen, auch während eines Schließ-Timers.
    document.addEventListener('contextmenu', function (e) {
      if (active && !active.panel.hidden && active.panel.contains(e.target)) {
        e.preventDefault();
        activateItem(e.target, active.close);
        return;
      }
      closeAll();
    }, true);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAll(); });
    // Fixes Menü soll nicht mitschweben — aber NUR schließen, wenn der gescrollte Container das
    // Menü wirklich bewegt: Dokument/Fenster oder ein Vorfahr des Panels. Capture fängt sonst
    // JEDES Scroll-Event der Seite (Carousel-Autoplay scrollt z.B. alle 3s programmatisch —
    // das schloss jedes offene Menü, egal wo die Maus war). Scrollen IM Panel selbst
    // (overflow des Menüs) schließt ebenfalls nicht.
    window.addEventListener('scroll', function (e) {
      var t = e.target;
      registry.forEach(function (m) {
        if (m.panel.hidden) return;
        if (t === document || t === window || (t !== m.panel && t.contains && t.contains(m.panel))) m.close();
      });
    }, true);

    // Auto-Schließen beim Verlassen: bewusst NICHT über mouseleave am Panel — das Panel öffnet
    // unter dem Zeiger (fixed), da feuert kein zuverlässiges mouseenter/leave. Stattdessen prüfen
    // wir bei jeder Zeigerbewegung DOM-basiert, ob der Zeiger noch im Panel ist (elementFromPoint
    // + panel.contains -> Untermenüs zählen mit, weil sie DOM-Kinder des Panels sind).
    document.addEventListener('pointermove', function (e) {
      var m = active;
      if (!m || m.panel.hidden || (m.mode !== 'leave' && m.mode !== 'leave-delay')) return;
      var x = e.clientX, y = e.clientY;
      // "auf dem Menü" = über dem Panel bzw. seinen DOM-Kindern (Untermenü zählt mit) ODER
      // innerhalb eines Toleranzsaums um das Panel-Rechteck. Der Saum federt ab, dass der Zeiger
      // beim Öffnen an der gerundeten Ecke knapp außerhalb sitzt und dass man die Kante kurz
      // übersteuert.
      var el = document.elementFromPoint(x, y);
      var r = m.panel.getBoundingClientRect();
      var inside = (el && m.panel.contains(el)) ||
                   (x >= r.left - HIT_SLOP && x <= r.right + HIT_SLOP &&
                    y >= r.top - HIT_SLOP && y <= r.bottom + HIT_SLOP);
      if (inside) {
        clearTimeout(m.timer); m.timer = null;                 // wieder drin -> Schließen abbrechen
      } else if (m.mode === 'leave') {
        m.close();                                             // sofort schließen
      } else if (m.timer === null) {
        m.timer = setTimeout(m.close, CLOSE_DELAY);            // leave-delay: verzögert
      }
    });
  }

  // ---- Kalender (Basecoat bringt keinen) ------------------------------------
  // Markup (alles über data-*): <div data-calendar class="w-fit rounded-lg border p-3"
  //   data-mode="single|range" data-month="YYYY-MM" data-months="1|2"
  //   data-selected="YYYY-MM-DD" | "YYYY-MM-DD/YYYY-MM-DD"
  //   [data-dropdown] [data-abbrev] [data-today="ring|bold"] [data-weekend="bold|color"]
  //   [data-holidays="YYYY-MM-DD,…"] [data-disabled="weekends|YYYY-MM-DD,…"]></div>
  // c22.js rendert Kopf + Raster (IMMER 6 Zeilen -> feste Höhe; "Heute" sitzt in der nie vollen
  // 6. Zeile), blättert Monate, wählt Tag/Bereich (auch über mehrere Monate). Datum-Rechnen macht
  // `Date`; Auswahl als 'YYYY-MM-DD'-String -> Vergleich per String.
  var CAL_MONTHS = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
  var CAL_WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  var CAL_ICO = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  // data-icon-lu = Lucide-Name (Icon-Registry, docs/icons.md) — Strings hier von Hand benannt,
  // tools/annotate-icons.py fasst nur statisches Markup in c22/components/*.html an.
  var CAL_PREV = '<svg data-icon-lu="chevron-left" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" ' + CAL_ICO + '><path d="m15 18-6-6 6-6"/></svg>';
  var CAL_NEXT = '<svg data-icon-lu="chevron-right" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" ' + CAL_ICO + '><path d="m9 18 6-6-6-6"/></svg>';
  var CAL_DOWN = '<svg data-icon-lu="chevron-down" class="ms-1 opacity-50" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="14" height="14" ' + CAL_ICO + '><path d="m6 9 6 6 6-6"/></svg>';
  var CAL_TODAY = '<svg data-icon-lu="calendar" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="13" height="13" ' + CAL_ICO + '><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/><path d="M8 2v4"/><path d="M16 2v4"/></svg>';
  var CAL_LEGEND_BG = { destructive: 'bg-destructive', warning: 'bg-warning', success: 'bg-success', primary: 'bg-primary', accent: 'bg-accent', 'muted-foreground': 'bg-muted-foreground' };

  function calPad(n) { return (n < 10 ? '0' : '') + n; }
  function calKey(y, m, d) { return y + '-' + calPad(m + 1) + '-' + calPad(d); }      // 'YYYY-MM-DD'
  function calNorm(str) { var p = String(str).split('-'); return calKey(+p[0], +p[1] - 1, +p[2]); }
  function calTrim(x) { return x.trim(); }
  function calEsc(x) { return String(x).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  function wireCalendar(el) {
    if (el.dataset.c22CalWired) return;
    el.dataset.c22CalWired = '1';
    var mode = el.dataset.mode || 'single';
    var nMonths = Math.max(1, +(el.dataset.months || 1));
    var hasDropdown = el.hasAttribute('data-dropdown');
    var abbrev = el.hasAttribute('data-abbrev');
    var todayStyle = el.dataset.today || 'ring';
    var weekendStyle = el.dataset.weekend || '';
    var legend = el.dataset.legend || '';   // "farbe:Label,farbe:Label" -> Punkt-Legende im Container
    var holidays = (el.dataset.holidays || '').split(',').map(calTrim).filter(Boolean);
    var disRaw = (el.dataset.disabled || '').split(',').map(calTrim).filter(Boolean);
    var disWeekends = disRaw.indexOf('weekends') >= 0;
    var disDates = disRaw.filter(function (x) { return x !== 'weekends'; });
    var clearable = el.hasAttribute('data-clearable');
    var now = new Date();
    var todayKey = calKey(now.getFullYear(), now.getMonth(), now.getDate());
    var s = { vy: now.getFullYear(), vm: now.getMonth(), sel: null, start: null, end: null, hover: null, ddOpen: false };
    if (el.dataset.month) { var mp = el.dataset.month.split('-'); s.vy = +mp[0]; s.vm = +mp[1] - 1; }
    if (mode === 'single' && el.dataset.selected) { s.sel = calNorm(el.dataset.selected); }
    if (mode === 'range' && el.dataset.selected) {
      var rp = el.dataset.selected.split('/'); s.start = calNorm(rp[0]); s.end = calNorm(rp[1] || rp[0]);
    }

    function monthName(m) { return abbrev ? CAL_MONTHS[m].slice(0, 3) : CAL_MONTHS[m]; }
    function navBtn(dir) {
      return '<button type="button" data-cal-' + dir + ' class="btn" data-variant="outline" data-size="icon-sm" aria-label="' +
        (dir === 'prev' ? 'Vorheriger' : 'Nächster') + ' Monat">' + (dir === 'prev' ? CAL_PREV : CAL_NEXT) + '</button>';
    }
    function ddItem(label, attr, current) {
      // Gewählte Zeile nach dem Auswahl-Kanon (components.css, [data-cal-menu] [aria-selected]):
      // fett + primary-gefüllt. hover:bg-accent nur auf UNGEWÄHLTEN Zeilen — die Utility würde
      // sonst die Füllung der gewählten Zeile beim Hovern übermalen (utilities-Layer gewinnt).
      var cls = 'flex w-full cursor-pointer items-center rounded-sm px-2 py-1.5 text-start text-sm' + (current ? '' : ' hover:bg-accent');
      return '<button type="button" ' + attr + (current ? ' aria-selected="true"' : '') + ' class="' + cls + '">' + label + '</button>';
    }
    function heute() {
      // data-clearable (Variante): „Löschen" entfernt die Auswahl — sitzt links neben „Heute".
      var loeschen = clearable
        ? '<button type="button" data-cal-clear class="text-muted-foreground hover:text-foreground inline-flex cursor-pointer items-center gap-1 text-xs font-medium"><svg data-icon-lu="x" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="13" height="13" ' + CAL_ICO + '><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>Löschen</button>'
        : '';
      return '<div class="flex h-full items-center justify-end gap-3 pe-1">' + loeschen +
        '<button type="button" data-cal-today class="text-muted-foreground hover:text-foreground inline-flex cursor-pointer items-center gap-1 text-xs font-medium">' + CAL_TODAY + 'Heute</button></div>';
    }
    function legendHtml() {   // Punkt-Legende im Container: data-legend="destructive:Wochenende,warning:Feiertag"
      if (!legend) return '';
      var items = legend.split(',').map(calTrim).filter(Boolean).map(function (it) {
        var i = it.indexOf(':'), bg = CAL_LEGEND_BG[it.slice(0, i).trim()] || 'bg-muted-foreground';
        return '<span class="flex items-center gap-1.5"><span class="' + bg + ' size-2 rounded-full"></span>' + calEsc(it.slice(i + 1).trim()) + '</span>';
      });
      return '<div class="text-muted-foreground mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1 px-1 text-xs">' + items.join('') + '</div>';
    }

    function head() {
      var h = '<div class="flex items-center justify-between gap-2 px-1 pb-3">' + navBtn('prev');
      if (hasDropdown) {
        h += '<div class="relative"><button type="button" data-cal-dd class="btn" data-variant="outline" data-size="sm" aria-expanded="' + (s.ddOpen ? 'true' : 'false') + '">' + monthName(s.vm) + ' ' + s.vy + CAL_DOWN + '</button>';
        if (s.ddOpen) {
          h += '<div data-cal-menu class="bg-popover text-popover-foreground ring-foreground/10 absolute left-1/2 top-full z-50 mt-1 flex -translate-x-1/2 gap-1 rounded-md p-1 shadow-md ring-1"><div class="pe-1">';
          for (var mi = 0; mi < 12; mi++) h += ddItem(CAL_MONTHS[mi], 'data-cal-month="' + mi + '"', mi === s.vm);
          h += '</div><div class="bg-border w-px self-stretch"></div><div class="ps-1">';
          for (var yy = s.vy - 3; yy <= s.vy + 3; yy++) h += ddItem(String(yy), 'data-cal-year="' + yy + '"', yy === s.vy);
          h += '</div></div>';
        }
        h += '</div>';
      } else {
        h += '<div class="text-sm font-medium">' + monthName(s.vm) + ' ' + s.vy + '</div>';
      }
      return h + navBtn('next') + '</div>';
    }

    function cell(y, m, day) {
      var key = calKey(y, m, day);
      var dow = new Date(y, m, day).getDay();
      var wknd = dow === 0 || dow === 6;
      if ((disWeekends && wknd) || disDates.indexOf(key) >= 0) {
        return '<td><button type="button" disabled aria-disabled="true" class="text-muted-foreground size-9 cursor-not-allowed rounded-md line-through opacity-50">' + day + '</button></td>';
      }
      var SEL = '<button type="button" data-cal-day="' + key + '" aria-selected="true" class="size-9 rounded-md bg-primary text-primary-foreground hover:bg-primary/90">' + day + '</button>';
      if (mode === 'range') {
        // Band-Grenzen: fertiger Bereich (start..end) ODER Vorschau bis zum Zeiger (start..hover).
        var lo = null, hi = null, other = s.end || s.hover;
        if (s.start && other) { lo = s.start < other ? s.start : other; hi = s.start < other ? other : s.start; }
        var inBand = lo && lo !== hi && key >= lo && key <= hi;
        var tdc = inBand ? ('bg-foreground/10' + (key === lo ? ' rounded-l-md' : '') + (key === hi ? ' rounded-r-md' : '')) : '';
        if (key === s.start || key === s.end) return '<td class="' + tdc + '">' + SEL + '</td>';   // schwarze Endpunkte
        if (inBand) return '<td class="' + tdc + '"><button type="button" data-cal-day="' + key + '" class="size-9">' + day + '</button></td>';
      } else if (s.sel === key) {
        return '<td>' + SEL + '</td>';
      }
      var x = 'size-9 rounded-md hover:bg-accent';
      if (key === todayKey) x += todayStyle === 'bold' ? ' font-bold underline underline-offset-2' : ' ring-1 ring-inset ring-foreground/30';
      if (weekendStyle === 'bold' && wknd) x += ' font-bold';
      if (weekendStyle === 'color' && wknd) x += ' text-destructive';
      if (holidays.indexOf(key) >= 0) x += ' text-warning font-semibold';
      return '<td><button type="button" data-cal-day="' + key + '" class="' + x + '">' + day + '</button></td>';
    }

    function grid(y, m, withHeute) {
      var h = '<table class="text-sm [&_td]:p-0"><thead><tr class="text-muted-foreground">';
      for (var w = 0; w < 7; w++) h += '<th class="size-9 font-normal">' + CAL_WEEKDAYS[w] + '</th>';
      h += '</tr></thead><tbody>';
      var startCol = (new Date(y, m, 1).getDay() + 6) % 7;
      var days = new Date(y, m + 1, 0).getDate();
      var day = 1;
      for (var row = 0; row < 6; row++) {           // IMMER 6 Zeilen -> feste Höhe
        h += '<tr>';
        for (var col = 0; col < 7; col++) {
          var blank = (row === 0 && col < startCol) || day > days;
          if (row === 5 && blank) {                 // 6. Zeile ist nie voll -> "Heute" rechts hinein
            h += '<td colspan="' + (7 - col) + '" class="h-9">' + (withHeute ? heute() : '') + '</td>';
            break;
          }
          if (blank) h += '<td class="h-9"></td>';
          else { h += cell(y, m, day); day++; }
        }
        h += '</tr>';
      }
      return h + '</tbody></table>';
    }

    function render() {
      if (nMonths > 1) {
        var h = '<div class="flex flex-col gap-4 sm:flex-row sm:gap-6">';
        for (var i = 0; i < nMonths; i++) {
          var dt = new Date(s.vy, s.vm + i, 1), y = dt.getFullYear(), m = dt.getMonth(), last = i === nMonths - 1;
          h += '<div><div class="flex items-center justify-between px-1 pb-3">' +
            (i === 0 ? navBtn('prev') : '<div class="size-8"></div>') +
            '<div class="text-sm font-medium">' + monthName(m) + ' ' + y + '</div>' +
            (last ? navBtn('next') : '<div class="size-8"></div>') +
            '</div>' + grid(y, m, last) + '</div>';
        }
        el.innerHTML = h + '</div>' + legendHtml();
      } else {
        el.innerHTML = head() + grid(s.vy, s.vm, true) + legendHtml();
      }
    }

    function shift(delta) { var d = new Date(s.vy, s.vm + delta, 1); s.vy = d.getFullYear(); s.vm = d.getMonth(); }
    function pick(key) {
      if (mode === 'range') {
        if (!s.start || s.end) { s.start = key; s.end = null; }
        else if (key < s.start) { s.end = s.start; s.start = key; }
        else { s.end = key; }
      } else { s.sel = key; }
      el.dispatchEvent(new CustomEvent('c22:calendar-change', { bubbles: true, detail: { mode: mode, selected: s.sel, start: s.start, end: s.end } }));
    }

    el.addEventListener('click', function (e) {
      var t = e.target.closest('button');
      if (!t || !el.contains(t)) return;
      var dirty = true;
      if (t.hasAttribute('data-cal-prev')) { shift(-1); }
      else if (t.hasAttribute('data-cal-next')) { shift(1); }
      else if (t.hasAttribute('data-cal-dd')) { e.stopPropagation(); s.ddOpen = !s.ddOpen; }
      else if (t.hasAttribute('data-cal-month')) { s.vm = +t.getAttribute('data-cal-month'); s.ddOpen = false; }
      else if (t.hasAttribute('data-cal-year')) { s.vy = +t.getAttribute('data-cal-year'); s.ddOpen = false; }
      else if (t.hasAttribute('data-cal-today')) { var td = new Date(); s.vy = td.getFullYear(); s.vm = td.getMonth(); s.ddOpen = false; }
      else if (t.hasAttribute('data-cal-clear')) {
        s.sel = null; s.start = null; s.end = null; s.hover = null;
        el.dispatchEvent(new CustomEvent('c22:calendar-change', { bubbles: true, detail: { mode: mode, selected: null, start: null, end: null } }));
      }
      else if (t.hasAttribute('data-cal-day')) { pick(t.getAttribute('data-cal-day')); }
      else dirty = false;
      // Rendern erst NACH dem Bubbling: render() ersetzt das Raster per innerHTML — käme der
      // Klick danach bei document an, wäre der geklickte Button bereits ausgehängt, und Zuhörer
      // mit `panel.contains(e.target)` (Basecoat-Popover im Date Picker) hielten den Klick für
      // „außerhalb" und schlössen das Popover. setTimeout(0) lässt das Event fertig durchlaufen.
      if (dirty) setTimeout(render, 0);
    });
    // Bereich-Vorschau: nach dem Start-Klick das graue Band live bis zum Zeiger ziehen.
    el.addEventListener('mouseover', function (e) {
      if (mode !== 'range' || !s.start || s.end) return;
      var t = e.target.closest('[data-cal-day]');
      var key = t ? t.getAttribute('data-cal-day') : null;
      if (key !== s.hover) { s.hover = key; render(); }
    });
    el.addEventListener('mouseleave', function () {
      if (mode === 'range' && s.hover != null) { s.hover = null; render(); }
    });
    document.addEventListener('click', function (e) { if (s.ddOpen && !el.contains(e.target)) { s.ddOpen = false; render(); } });
    // Von außen setzen (Date Picker per Texteingabe): Auswahl übernehmen UND den Monat der
    // Auswahl anzeigen — Gegenstück zum c22:calendar-change-Event nach draußen.
    el.addEventListener('c22:calendar-set', function (e) {
      var key = e.detail && e.detail.selected;
      if (!key || mode !== 'single') return;
      s.sel = calNorm(key);
      var p = s.sel.split('-'); s.vy = +p[0]; s.vm = +p[1] - 1;
      render();
    });

    render();
  }

  // ---- Uhrzeit-Bausteine für den Date Picker --------------------------------
  // <div data-clock data-value="HH:MM" [data-input] [data-for="input-id"]> — Zifferblatt im
  //   Android-Stil: Stundenwahl in zwei Ringen (außen 1–12, innen 13–00), nach der Stundenwahl
  //   automatisch Minuten (5er-Raster); Zeiger + gewählte Kappe primary. Kopf wahlweise als
  //   klickbares HH:MM (Standard) oder mit data-input als echtes Eingabefeld: nur Ziffern/':',
  //   ':' wird bei 4 Ziffern automatisch gesetzt (1100 -> 11:00), Caret-Position wählt den
  //   Modus (vor dem ':' Stunden, dahinter Minuten). data-for hält ein externes Feld synchron.
  // <div data-time-stepper data-value="HH:MM" [data-for]> — hoch/runter je Spalte: Minuten in
  //   15er-Schritten (00/15/30/45) mit Stundenübertrag, Stunden ±1 mit 23↔0-Umlauf.
  var CK_UP = '<svg data-icon-lu="chevron-up" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" ' + CAL_ICO + '><path d="m18 15-6-6-6 6"/></svg>';
  var CK_DOWN = '<svg data-icon-lu="chevron-down" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" ' + CAL_ICO + '><path d="m6 9 6 6 6-6"/></svg>';

  function ckParse(v) {
    var t = String(v || '').trim();
    var m = /^(\d{1,2}):(\d{2})$/.exec(t);
    if (!m && /^\d{3,4}$/.test(t)) m = [t, t.slice(0, t.length - 2), t.slice(-2)];   // 130/1100 ohne Doppelpunkt
    return m && +m[1] < 24 && +m[2] < 60 ? { h: +m[1], m: +m[2] } : null;
  }

  function wireClock(el) {
    if (el.dataset.c22ClockWired) return;
    el.dataset.c22ClockWired = '1';
    var t0 = ckParse(el.dataset.value) || { h: 12, m: 0 };
    var s = { h: t0.h, m: t0.m, mode: 'h' };
    var inp = el.dataset.for ? document.getElementById(el.dataset.for) : null;
    // data-input: statt des klickbaren HH:MM-Kopfs ein echtes Eingabefeld über dem Zifferblatt.
    // Kopf und Zifferblatt sind getrennte Behälter: der Input wird NIE mit neu gerendert
    // (sonst verlöre er beim Tippen den Fokus), nur das Zifferblatt.
    var withInput = el.hasAttribute('data-input');
    el.innerHTML = '<div data-ck-head></div><div data-ck-dial></div>';
    var headBox = el.querySelector('[data-ck-head]');
    var dialBox = el.querySelector('[data-ck-dial]');
    var tIn = null;
    if (withInput) {
      // block: .input ist inline-block — ohne block greift mx-auto nicht und das Feld klebt links
      headBox.innerHTML = '<input class="input mx-auto mb-3 block w-24 text-center tabular-nums" inputmode="numeric" placeholder="hh:mm" aria-label="Uhrzeit">';
      tIn = headBox.querySelector('input');
      tIn.value = calPad(s.h) + ':' + calPad(s.m);
    }

    function push() {
      var v = calPad(s.h) + ':' + calPad(s.m);
      if (tIn) tIn.value = v;
      if (inp) inp.value = v;
      el.dispatchEvent(new CustomEvent('c22:clock-change', { bubbles: true, detail: { hour: s.h, minute: s.m, value: v } }));
    }
    // Kappen sitzen per Trigonometrie auf dem Ring — left/top sind Geometrie, keine Optik
    // (Farben/Größen kommen weiter aus Token-Klassen).
    function ring(vals, r, attr, cur, muted) {
      var h = '', C = 112;
      vals.forEach(function (v) {
        var a = ((attr === 'data-ck-min' ? v * 6 : (v % 12) * 30) - 90) * Math.PI / 180;
        // Hover kommt aus components.css (Schleier) — accent ging auf dem muted-Zifferblatt unter.
        var cls = v === cur ? 'bg-primary text-primary-foreground' : (muted ? 'text-muted-foreground' : '');
        h += '<button type="button" ' + attr + '="' + v + '"' + (v === cur ? ' aria-pressed="true"' : '') + ' class="absolute flex size-8 -translate-x-1/2 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full text-sm tabular-nums ' + cls +
          '" style="left:' + Math.round(C + r * Math.cos(a)) + 'px;top:' + Math.round(C + r * Math.sin(a)) + 'px">' + (v === 0 || attr === 'data-ck-min' ? calPad(v) : v) + '</button>';
      });
      return h;
    }
    function renderHead() {
      if (withInput) return;   // der Input steht, wird nur per push() aktualisiert
      var segc = 'cursor-pointer rounded px-0.5 tabular-nums ';
      headBox.innerHTML = '<div class="flex items-center justify-center pb-3 text-xl font-medium">' +
        '<button type="button" data-ck-mode="h" class="' + segc + (s.mode === 'h' ? 'text-primary' : 'text-muted-foreground hover:text-foreground') + '">' + calPad(s.h) + '</button><span class="text-muted-foreground">:</span>' +
        '<button type="button" data-ck-mode="m" class="' + segc + (s.mode === 'm' ? 'text-primary' : 'text-muted-foreground hover:text-foreground') + '">' + calPad(s.m) + '</button></div>';
    }
    function renderDial() {
      var r = s.mode === 'h' ? (s.h === 0 || s.h > 12 ? 56 : 88) : 88;
      var ang = s.mode === 'h' ? (s.h % 12) * 30 : s.m * 6;
      var len = r - 16;
      var dial = '<div class="bg-muted relative size-56 rounded-full">' +
        '<div class="bg-primary absolute w-0.5 origin-bottom" style="left:111px;top:' + (112 - len) + 'px;height:' + len + 'px;transform:rotate(' + ang + 'deg)"></div>' +
        '<div class="bg-primary absolute size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style="left:112px;top:112px"></div>';
      if (s.mode === 'h') {
        dial += ring([12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], 88, 'data-ck-hour', s.h, false);
        dial += ring([0, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23], 56, 'data-ck-hour', s.h, true);
      } else {
        dial += ring([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55], 88, 'data-ck-min', s.m, false);
      }
      dialBox.innerHTML = dial + '</div>';
    }
    function render() { renderHead(); renderDial(); }

    el.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b || !el.contains(b)) return;
      var dirty = true;
      if (b.hasAttribute('data-ck-mode')) { s.mode = b.getAttribute('data-ck-mode'); }
      else if (b.hasAttribute('data-ck-hour')) { s.h = +b.getAttribute('data-ck-hour'); s.mode = 'm'; push(); }
      else if (b.hasAttribute('data-ck-min')) { s.m = +b.getAttribute('data-ck-min'); push(); }
      else dirty = false;
      if (dirty) setTimeout(render, 0);   // wie beim Kalender: erst nach dem Bubbling neu rendern
    });
    if (tIn) {
      // Nur Ziffern und ':' zulassen; bei 4 Ziffern den ':' automatisch setzen (1100 -> 11:00).
      // 3-stellige Eingaben (130 = 1:30) versteht ckParse auch ohne ':' — normalisiert wird
      // beim Verlassen, nicht mitten im Tippen (sonst käme aus „110" fälschlich „1:10…").
      tIn.addEventListener('input', function () {
        var v = tIn.value.replace(/[^\d:]/g, '');
        var d = v.replace(/:/g, '');
        if (v.indexOf(':') < 0 && d.length === 4) v = d.slice(0, 2) + ':' + d.slice(2);
        if (v !== tIn.value) tIn.value = v;
        var p = ckParse(v);
        if (p) { s.h = p.h; s.m = p.m; renderDial(); }   // Kopf-Input NICHT anfassen (Fokus/Caret)
      });
      tIn.addEventListener('blur', function () {
        var p = ckParse(tIn.value);
        if (p) { s.h = p.h; s.m = p.m; push(); render(); }
        else tIn.value = calPad(s.h) + ':' + calPad(s.m);   // Unlesbares verwerfen
      });
      // Caret steuert das Zifferblatt: vor dem ':' = Stundenwahl, dahinter = Minutenwahl.
      function modeFromCaret() {
        var i = (tIn.value || '').indexOf(':');
        var mode = i >= 0 && tIn.selectionStart > i ? 'm' : 'h';
        if (mode !== s.mode) { s.mode = mode; renderDial(); }
      }
      tIn.addEventListener('click', modeFromCaret);
      tIn.addEventListener('keyup', modeFromCaret);
      tIn.addEventListener('focus', function () { setTimeout(modeFromCaret, 0); });
    }
    if (inp) inp.addEventListener('input', function () {
      var v = ckParse(inp.value);
      if (v) { s.h = v.h; s.m = v.m; render(); }
    });
    render();
  }

  function wireTimeStepper(el) {
    if (el.dataset.c22TsWired) return;
    el.dataset.c22TsWired = '1';
    var t0 = ckParse(el.dataset.value) || { h: 12, m: 0 };
    var s = { h: t0.h, m: t0.m };
    var inp = el.dataset.for ? document.getElementById(el.dataset.for) : null;

    function push() {
      var v = calPad(s.h) + ':' + calPad(s.m);
      if (inp) inp.value = v;
      el.dispatchEvent(new CustomEvent('c22:time-change', { bubbles: true, detail: { hour: s.h, minute: s.m, value: v } }));
    }
    function col(unit, val) {
      var name = unit === 'h' ? 'Stunde' : 'Minuten';
      function b(dir, lbl, ico) {
        return '<button type="button" data-tsp="' + unit + dir + '" class="btn" data-variant="ghost" data-size="icon-sm" aria-label="' + name + ' ' + lbl + '">' + ico + '</button>';
      }
      // Wert ist ein ECHTES Eingabefeld (PO 22d: Uhrzeit auch eintippbar) — rahmenlos,
      // nur Ziffern; beim Verlassen wird normalisiert (blur -> render).
      return '<div class="flex flex-col items-center">' + b('+', 'hoch', CK_UP) +
        '<input data-tsp-val="' + unit + '" inputmode="numeric" maxlength="2" aria-label="' + name + '" value="' + calPad(val) + '"' +
        ' class="w-10 border-0 bg-transparent py-1 text-center text-lg font-medium tabular-nums outline-none">' + b('-', 'runter', CK_DOWN) + '</div>';
    }
    function render() {
      el.innerHTML = '<div class="flex items-center justify-center gap-2">' + col('h', s.h) +
        '<span class="text-muted-foreground text-lg font-medium">:</span>' + col('m', s.m) + '</div>';
    }
    el.addEventListener('click', function (e) {
      var b = e.target.closest('[data-tsp]');
      if (!b || !el.contains(b)) return;
      var k = b.getAttribute('data-tsp');
      if (k === 'h+') { s.h = (s.h + 1) % 24; }
      else if (k === 'h-') { s.h = (s.h + 23) % 24; }
      else if (k === 'm+') { s.m = s.m % 15 ? Math.ceil(s.m / 15) * 15 : s.m + 15; if (s.m >= 60) { s.m -= 60; s.h = (s.h + 1) % 24; } }
      else if (k === 'm-') { s.m = s.m % 15 ? Math.floor(s.m / 15) * 15 : s.m - 15; if (s.m < 0) { s.m += 60; s.h = (s.h + 23) % 24; } }
      else return;
      push();
      setTimeout(render, 0);
    });
    // Tippen: Ziffern filtern, gültige Werte sofort übernehmen (kein Re-Render — Fokus!);
    // beim Verlassen normalisieren (auf zwei Stellen, ungültiges verwerfen).
    el.addEventListener('input', function (e) {
      var f = e.target.closest('[data-tsp-val]');
      if (!f) return;
      var ziffern = f.value.replace(/\D/g, '').slice(0, 2);
      if (f.value !== ziffern) f.value = ziffern;
      if (ziffern === '') return;
      var num = +ziffern;
      if (f.getAttribute('data-tsp-val') === 'h') {
        if (num <= 23) { s.h = num; push(); }
        // Durchschreiben (PO 22d): zwei Stunden-Ziffern -> weiter ins Minutenfeld,
        // Inhalt vorgewählt, damit „0745" in einem Zug durchläuft.
        if (ziffern.length === 2) {
          var mm = el.querySelector("[data-tsp-val='m']");
          if (mm) { mm.focus(); mm.select(); }
        }
      } else if (num <= 59) { s.m = num; push(); }
    });
    // Rückwärts löschen läuft vom leeren Minutenfeld ins Stundenfeld weiter (PO 22d).
    el.addEventListener('keydown', function (e) {
      if (e.key !== 'Backspace') return;
      var f = e.target.closest("[data-tsp-val='m']");
      if (!f) return;
      if (f.value === '' || (f.selectionStart === 0 && f.selectionEnd === 0)) {
        var hh = el.querySelector("[data-tsp-val='h']");
        if (hh) {
          e.preventDefault();
          hh.value = hh.value.slice(0, -1);
          hh.focus();
          hh.setSelectionRange(hh.value.length, hh.value.length);
          hh.dispatchEvent(new Event('input', { bubbles: true }));
        }
      }
    });
    el.addEventListener('focusout', function (e) {
      // Nur normalisieren, wenn der Fokus die Stepper-Felder wirklich verlässt —
      // beim Durchschreiben (h -> m) würde ein Re-Render den Fokussprung zerstören.
      if (!e.target.closest('[data-tsp-val]')) return;
      if (e.relatedTarget && el.contains(e.relatedTarget)) return;
      render();
    });
    render();
  }

  // Textaffixe im input-group (PO 32d): tippt jemand den angezeigten Präfix/Suffix mit
  // (z.B. „https://example.com" trotz https://-Präfix), streift das Feld ihn ab.
  function wireAffixStrip(group) {
    if (group.dataset.c22AffixWired) return;
    group.dataset.c22AffixWired = '1';
    var inp = group.querySelector(':scope > input');
    if (!inp) return;
    function textAffix(span) {
      // Nur reine Text-Spans zählen (keine Icon-/kbd-Behälter).
      return span && !span.querySelector('svg, kbd') ? span.textContent.trim() : '';
    }
    // Klick auf ein Text-Affix (Präfix/Suffix/Zähler-Span) fokussiert das Feld — die Spans
    // gehören optisch zur Feldfläche (PO 32d).
    group.addEventListener('click', function (e) {
      if (e.target.closest('span') && !e.target.closest('button, a, input, kbd')) inp.focus();
    });
    // Erst beim VERLASSEN des Feldes strippen (change), nicht beim Tippen — live wirkte es,
    // als würden Zeichen verschwinden (PO).
    inp.addEventListener('change', function () {
      var pre = '', suf = '', s = inp.previousElementSibling, e = inp.nextElementSibling;
      if (s && s.tagName === 'SPAN') pre = textAffix(s);
      if (e && e.tagName === 'SPAN') suf = textAffix(e);
      var v = inp.value;
      if (pre && v.startsWith(pre)) v = v.slice(pre.length);
      if (suf && v.endsWith(suf) && v !== suf) v = v.slice(0, -suf.length);
      if (v !== inp.value) inp.value = v;
    });
  }

  // Passwort-Auge (PO 32f): STANDARD zeigt das Passwort nur, SOLANGE gedrückt wird
  // (pointerdown/-up, wie ein Guckloch); data-password-toggle="toggle" ist die Variante,
  // bei der ein Klick dauerhaft umschaltet. Icon wechselt per CSS über aria-pressed.
  function wirePasswordToggle(btn) {
    if (btn.dataset.c22PwWired) return;
    btn.dataset.c22PwWired = '1';
    function setzen(zeigen) {
      var group = btn.closest('.input-group');
      var inp = group && group.querySelector("input[type='password'], input[data-pw='1']");
      if (!inp) return;
      inp.dataset.pw = '1';                       // wiederfindbar, wenn type gerade text ist
      inp.type = zeigen ? 'text' : 'password';
      btn.setAttribute('aria-pressed', zeigen ? 'true' : 'false');
      btn.setAttribute('aria-label', zeigen ? 'Passwort verbergen' : 'Passwort anzeigen');
    }
    if (btn.dataset.passwordToggle === 'toggle') {
      btn.addEventListener('click', function () {
        setzen(btn.getAttribute('aria-pressed') !== 'true');
      });
    } else {
      btn.addEventListener('pointerdown', function () { setzen(true); });
      ['pointerup', 'pointerleave', 'pointercancel'].forEach(function (ev) {
        btn.addEventListener(ev, function () { setzen(false); });
      });
    }
  }

  // Lösch-X im Feld (PO 32b): leert das Feld und fokussiert es; Sichtbarkeit steuert CSS
  // (nur wenn Text im Feld — :placeholder-shown).
  function wireClearButton(btn) {
    if (btn.dataset.c22ClearWired) return;
    btn.dataset.c22ClearWired = '1';
    btn.addEventListener('click', function () {
      var group = btn.closest('.input-group, .relative');
      var inp = group && group.querySelector('input, textarea');
      if (!inp) return;
      inp.value = '';
      inp.focus();
      inp.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  // Zahl-Stepper (PO: Standard-Zahlfeld ist ohne Pfeile; diese Variante bringt eigene).
  function wireNumberStep(btn) {
    if (btn.dataset.c22NumWired) return;
    btn.dataset.c22NumWired = '1';
    btn.addEventListener('click', function () {
      var group = btn.closest('.input-group');
      var inp = group && group.querySelector("input[type='number']");
      if (!inp) return;
      if (btn.dataset.numberStep === 'up') inp.stepUp(); else inp.stepDown();
      inp.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  // OTP-Felder (.input-otp-slot) — Tippen springt automatisch ins nächste Feld (PO):
  // Backspace leert ein gefülltes Feld und BLEIBT dort (die nächste Eingabe gehört in die
  // frei gewordene Stelle); erst in einem leeren Feld springt es zurück und leert das
  // vorige. Fokus markiert den Inhalt, damit Tippen ein beschriebenes Feld
  // ÜBERSCHREIBT (maxlength=1 würde die Eingabe sonst schlucken). Zeichenfilter kommt aus
  // dem pattern-Attribut des Slots; Einfügen verteilt den Code ab dem fokussierten Feld.
  function wireOtp(inp) {
    if (inp.dataset.c22OtpWired) return;
    inp.dataset.c22OtpWired = '1';
    var slots = Array.prototype.slice.call(inp.parentElement.querySelectorAll('.input-otp-slot'));
    var re = new RegExp('^' + (inp.getAttribute('pattern') || '[0-9]*').replace(/\*$/, '') + '$');
    function geheZu(i) {
      if (i < 0 || i >= slots.length) return;
      slots[i].focus();
      slots[i].select();
    }
    inp.addEventListener('focus', function () {
      setTimeout(function () { inp.select(); }, 0);   // nach dem Maus-Klick, der die Auswahl sonst kollabiert
    });
    inp.addEventListener('input', function () {
      var ch = inp.value.slice(-1);
      if (!ch) return;
      if (!re.test(ch)) { inp.value = ''; return; }
      inp.value = ch;
      geheZu(slots.indexOf(inp) + 1);
    });
    inp.addEventListener('keydown', function (e) {
      var i = slots.indexOf(inp);
      if (e.key === 'Backspace') {
        e.preventDefault();
        // Gefülltes Feld: nur leeren, Fokus BLEIBT — die nächste Eingabe gehört hierhin,
        // nicht ins vorige Feld (PO). Erst Backspace im leeren Feld springt zurück.
        if (inp.value) { inp.value = ''; }
        else if (i > 0) { slots[i - 1].value = ''; geheZu(i - 1); }
      } else if (e.key === 'ArrowLeft') { e.preventDefault(); geheZu(i - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); geheZu(i + 1); }
    });
    inp.addEventListener('paste', function (e) {
      var text = (e.clipboardData || window.clipboardData).getData('text') || '';
      e.preventDefault();
      var i = slots.indexOf(inp);
      Array.prototype.forEach.call(text.replace(/\s/g, ''), function (ch) {
        if (i >= slots.length || !re.test(ch)) return;
        slots[i].value = ch;
        i += 1;
      });
      geheZu(Math.min(i, slots.length - 1));
    });
  }

  // Resizable-Trennlinie (47, shadcn-Stil): Ziehen ändert die flex-basis des Panels VOR
  // der Linie (min-/max-Grenzen kommen von dessen min-w/max-w-Klassen). STANDARD zieht
  // nur der Griff (PO); [data-resize-handle="line"] zieht an der ganzen Linie.
  // Vertikal (flex-col-Container) wird automatisch erkannt.
  function wireResizeHandle(h) {
    if (h.dataset.c22RszWired) return;
    h.dataset.c22RszWired = '1';
    var panel = h.previousElementSibling;
    if (!panel) return;
    var nurGriff = h.getAttribute('data-resize-handle') !== 'line';
    h.addEventListener('pointerdown', function (e) {
      if (nurGriff && !e.target.closest('[data-resize-grip]')) return;
      e.preventDefault();
      h.setPointerCapture(e.pointerId);
      var vertikal = getComputedStyle(h.parentElement).flexDirection === 'column';
      var start = vertikal ? e.clientY : e.clientX;
      var basis = vertikal ? panel.getBoundingClientRect().height : panel.getBoundingClientRect().width;
      function ziehen(ev) {
        var d = (vertikal ? ev.clientY : ev.clientX) - start;
        panel.style.flexBasis = Math.max(0, basis + d) + 'px';
        panel.style.flexGrow = '0';
        panel.style.flexShrink = '0';
      }
      function loslassen(ev) {
        h.releasePointerCapture(ev.pointerId);
        h.removeEventListener('pointermove', ziehen);
        h.removeEventListener('pointerup', loslassen);
      }
      h.addEventListener('pointermove', ziehen);
      h.addEventListener('pointerup', loslassen);
    });
  }

  // Nachricht löschen (Message-Fußzeilen-Kanon): entfernt die eigene Nachricht aus dem
  // Verlauf (reine Demo-Logik — die App bindet das an ihr Backend).
  function wireMessageDelete(btn) {
    if (btn.dataset.c22DelWired) return;
    btn.dataset.c22DelWired = '1';
    btn.addEventListener('click', function () {
      var msg = btn.closest('.message');
      if (msg) msg.remove();
    });
  }

  // Dropdowns in scrollenden Tabellen (PO 21): .table-container (overflow-x-auto)
  // clippt absolute Popover — und schon die GESCHLOSSENEN (opacity-0, absolut) blähen
  // den Scrollbereich auf, der Container zeigte dauerhaft einen springenden
  // Scrollbalken. Daher: Popover ab Verdrahtung dauerhaft fix zum Viewport (raus aus
  // dem Container-Fluss); beim Öffnen kommen die Koordinaten (data-side="left" links
  // neben den Trigger, sonst darunter, an den Viewport geklemmt).
  function wireTableMenu(dd) {
    if (dd.dataset.c22TmWired) return;
    dd.dataset.c22TmWired = '1';
    // Trigger über aria-expanded finden — Popover-Trigger tragen KEIN aria-haspopup
    // (nur Menü-Trigger), sonst blieben Filter-Popover absolut im Container hängen.
    var trigger = dd.querySelector('button[aria-expanded]');
    var pop = dd.querySelector('[data-popover]');
    if (!trigger || !pop) return;
    pop.style.position = 'fixed';
    pop.style.right = 'auto';
    // Vendor gibt [data-popover] min-w-full — bezogen auf die kleine Hülle harmlos,
    // bei position:fixed aber plötzlich Viewport-Breite. Eigenbreite (w-*-Klasse
    // bzw. w-max) gilt weiter.
    pop.style.minWidth = '0px';
    function setzen() {
      if (trigger.getAttribute('aria-expanded') !== 'true') return;
      var r = trigger.getBoundingClientRect();
      // offsetWidth/-Height statt Rect: die Öffnungsanimation skaliert das Popover
      // (scale .95) — das Rect wäre mitten in der Animation zu klein gemessen.
      var bw = pop.offsetWidth;
      var bh = pop.offsetHeight;
      var links = (pop.dataset.side || '') === 'left';
      // Standard (PO 21f): unter dem Trigger, Start-bündig — das Menü wächst nach
      // RECHTS (an den Viewport geklemmt); data-side="left" öffnet links daneben.
      var x = links ? r.left - bw - 4 : Math.min(r.left, window.innerWidth - bw - 8);
      var y = links ? r.top : r.bottom + 4;
      if (y + bh > window.innerHeight - 8) y = Math.max(8, window.innerHeight - bh - 8);
      // Koordinaten OHNE Übergang setzen: Vendor-Transitions animieren sonst auch
      // left/top — das Menü „flog" beim ersten Öffnen von der Auto-Position herein.
      var altTrans = pop.style.transition;
      pop.style.transition = 'none';
      pop.style.left = Math.max(8, x) + 'px';
      pop.style.top = y + 'px';
      void pop.offsetWidth;
      pop.style.transition = altTrans;
    }
    new MutationObserver(setzen).observe(trigger, { attributes: true, attributeFilter: ['aria-expanded'] });
  }

  // Filter-Combobox (Combobox „Als Filter", PO 18/21): komplette Mehrfachauswahl-
  // Combobox IN einem Popover — wie 18e inklusive CHIPS mit Entfernen-X (gleiche
  // Vendor-Klassen .combobox-chip/-chip-remove wie die Multi-Combobox). Das
  // Suchfeld filtert die Liste, Klick auf eine Option togglet aria-selected
  // (Haken-Kanon), [data-fc-leer] zeigt den Leer-Hinweis. Jede Änderung feuert
  // 'c22-fc-change' (bubbelt — Data Table hört darauf).
  function wireFilterCombo(panel) {
    if (panel.dataset.c22FcWired) return;
    panel.dataset.c22FcWired = '1';
    var chips = panel.querySelector('[data-fc-chips]');
    var eingabe = panel.querySelector('input');
    var liste = panel.querySelector("[role='listbox']");
    var leer = panel.querySelector('[data-fc-leer]');
    if (!liste) return;
    function chipsMalen() {
      if (!chips) return;
      chips.querySelectorAll('.combobox-chip').forEach(function (c) { c.remove(); });
      // Chips nur bei WIRKLICH aktivem Filter (PO 21): sind alle Werte gewählt,
      // filtert nichts — dann bleibt das Feld leer statt alles aufzuzählen.
      var alleOpt = liste.querySelectorAll("[role='option']");
      var gewaehlt = liste.querySelectorAll("[role='option'][aria-selected='true']");
      if (gewaehlt.length === alleOpt.length) return;
      gewaehlt.forEach(function (o) {
        var chip = document.createElement('span');
        chip.className = 'combobox-chip';
        var label = document.createElement('span');
        label.textContent = o.textContent.trim();
        var entf = document.createElement('button');
        entf.type = 'button';
        entf.className = 'combobox-chip-remove btn';
        entf.dataset.variant = 'ghost';
        entf.dataset.size = 'icon-xs';
        entf.setAttribute('aria-label', o.textContent.trim() + ' entfernen');
        entf.innerHTML = '<svg data-icon-lu="x" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
        entf.addEventListener('click', function (e) {
          e.stopPropagation();
          o.setAttribute('aria-selected', 'false');
          aendern();
        });
        chip.appendChild(label);
        chip.appendChild(entf);
        chips.insertBefore(chip, eingabe && eingabe.parentElement === chips ? eingabe : null);
      });
    }
    function aendern() {
      chipsMalen();
      panel.dispatchEvent(new CustomEvent('c22-fc-change', { bubbles: true }));
    }
    if (eingabe) {
      eingabe.addEventListener('input', function () {
        var q = eingabe.value.trim().toLowerCase();
        var treffer = 0;
        liste.querySelectorAll("[role='option']").forEach(function (o) {
          var zeigt = !q || o.textContent.toLowerCase().indexOf(q) !== -1;
          o.hidden = !zeigt;
          if (zeigt) treffer++;
        });
        if (leer) leer.hidden = treffer > 0;
      });
    }
    liste.addEventListener('click', function (e) {
      var o = e.target.closest("[role='option']");
      if (!o) return;
      o.setAttribute('aria-selected', o.getAttribute('aria-selected') === 'true' ? 'false' : 'true');
      aendern();
    });
    // Externe Zustandsänderung (z.B. Data-Table-Zurücksetzen) -> Chips neu malen.
    panel.addEventListener('c22-fc-refresh', chipsMalen);
    chipsMalen();
  }

  // Data Table (21, data-datatable): macht die komponierten Tabellen-Muster echt —
  // Filter (data-dt-filter), Zeilenauswahl mit Zähler (data-dt-select/-select-all/-count),
  // Spalten ein-/ausblenden (data-dt-col im Spalten-Menü), Sortierung
  // (th-Button data-dt-sort="text|number|date", zyklisch asc/desc, aria-sort am th)
  // und Pagination (data-dt-pager/-prev/-next/-pages + data-dt-pagesize-Select).
  function wireDataTable(root) {
    if (root.dataset.c22DtWired) return;
    root.dataset.c22DtWired = '1';
    var tabelle = root.querySelector('table');
    if (!tabelle || !tabelle.tBodies.length) return;
    var koerper = tabelle.tBodies[0];
    var alleZeilen = Array.prototype.slice.call(koerper.rows);
    var filter = root.querySelector('[data-dt-filter]');
    var zaehler = root.querySelector('[data-dt-count]');
    var pager = root.querySelector('[data-dt-pager]');
    var seitenBox = root.querySelector('[data-dt-pages]');
    var groesseInput = root.querySelector('[data-dt-pagesize] input[type="hidden"]');
    var groesseRadio = root.querySelector('[data-dt-pagesize-opt][aria-checked="true"]');
    var seite = 1;
    var proSeite = groesseInput ? parseInt(groesseInput.value, 10) || 0
      : groesseRadio ? parseInt(groesseRadio.dataset.dtPagesizeOpt, 10) || 0 : 0;

    // Spaltenfilter (PO 21: Trichter-Icon je Spalte statt Freitextsuche): jede Listbox
    // mit data-dt-filter-col="<Spaltenindex>" ist eine Filter-Combobox (wireFilterCombo)
    // — eine Zeile bleibt sichtbar, solange ihr Zellwert in jeder gefilterten Spalte
    // noch angehakt ist. Ein Suchfeld (data-dt-filter) kann zusätzlich existieren.
    var spaltenMenues = Array.prototype.slice.call(root.querySelectorAll('[data-dt-filter-col]'));
    // Facetten-Semantik (PO 21, Datentabellen-Grundregel): KEIN Haken = KEIN Filter =
    // alles sichtbar. Ein Wert anklicken filtert AUF ihn (Haken + Chip), weitere
    // erweitern die Auswahl. Alle Werte angehakt wirkt wie kein Filter.
    function spaltenFilter() {
      return spaltenMenues.map(function (menue) {
        var erlaubt = [];
        var alle = menue.querySelectorAll("[role='option']");
        alle.forEach(function (o) {
          if (o.getAttribute('aria-selected') === 'true') erlaubt.push(o.textContent.trim());
        });
        return {
          idx: parseInt(menue.dataset.dtFilterCol, 10),
          erlaubt: erlaubt,
          aktiv: erlaubt.length > 0 && erlaubt.length < alle.length,
        };
      });
    }
    function sichtbare() {
      var q = filter ? filter.value.trim().toLowerCase() : '';
      var filterListe = spaltenFilter();
      return alleZeilen.filter(function (z) {
        if (q && z.textContent.toLowerCase().indexOf(q) === -1) return false;
        return filterListe.every(function (f) {
          if (!f.aktiv) return true;
          var zelle = z.cells[f.idx];
          return !zelle || f.erlaubt.indexOf(zelle.textContent.trim()) !== -1;
        });
      });
    }
    function zaehlerMalen() {
      var n = alleZeilen.filter(function (z) {
        var box = z.querySelector('[data-dt-select]');
        return box ? box.checked : z.dataset.state === 'selected';
      }).length;
      // Bulk-Element (PO): sitzt IN der Werkzeugzeile zwischen Suche und Icons —
      // Zähler + Dropdown-Pfeil mit den Sammel-Aktionen.
      var bulk = root.querySelector('[data-dt-bulkbar]');
      if (bulk) {
        bulk.toggleAttribute('hidden', n === 0);
        var bulkZaehler = bulk.querySelector('[data-dt-count-bulk]');
        if (bulkZaehler) bulkZaehler.textContent = n + ' ausgewählt';
        if (zaehler) zaehler.textContent = alleZeilen.length + ' Einträge';
        return;
      }
      if (!zaehler) return;
      // Ohne Auswahl steht die Gesamtzahl da (PO 21a) — die Zeile bleibt immer
      // sichtbar, damit der Seitenwechsler daneben nicht springt.
      zaehler.textContent = n > 0
        ? n + ' von ' + alleZeilen.length + ' Zeilen ausgewählt'
        : alleZeilen.length + ' Einträge';
    }
    function pagerMalen(seiten) {
      // Bei einer einzigen Seite („Alle anzeigen" oder wenig Einträge) verschwindet
      // die Navigation komplett.
      if (pager) pager.toggleAttribute('hidden', seiten <= 1);
      if (!seitenBox) return;
      seitenBox.textContent = '';
      for (var i = 1; i <= seiten; i++) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn';
        b.dataset.variant = i === seite ? 'outline' : 'ghost';
        b.dataset.size = 'icon';
        if (i === seite) b.setAttribute('aria-current', 'page');
        b.textContent = i;
        b.addEventListener('click', (function (nr) {
          return function () { seite = nr; malen(); };
        })(i));
        seitenBox.appendChild(b);
      }
      var vor = root.querySelector('[data-dt-prev]');
      var nach = root.querySelector('[data-dt-next]');
      if (vor) vor.disabled = seite <= 1;
      if (nach) nach.disabled = seite >= seiten;
    }
    function malen() {
      var s = sichtbare();
      var seiten = proSeite ? Math.max(1, Math.ceil(s.length / proSeite)) : 1;
      if (seite > seiten) seite = seiten;
      var start = proSeite ? (seite - 1) * proSeite : 0;
      var fenster = proSeite ? s.slice(start, start + proSeite) : s;
      alleZeilen.forEach(function (z) { z.hidden = fenster.indexOf(z) === -1; });
      if (pager) pagerMalen(seiten);
      // STANDARD (PO 21): FEHLENDE Einträge verkleinern die Tabelle nicht — die Höhe
      // des vollen Zustands (volle Seite bzw. alle Zeilen) bleibt als min-height
      // eingefroren, nichts schiebt sich. VARIANTE data-dt-shrink an der Hülle:
      // die Tabelle schrumpft mit dem Inhalt.
      var behaelter = root.querySelector('.table-container');
      if (behaelter && !root.hasAttribute('data-dt-shrink')) {
        var voll = proSeite || alleZeilen.length;
        if (fenster.length >= voll) {
          behaelter.style.minHeight = '';
          behaelter.style.minHeight = behaelter.offsetHeight + 'px';
        }
      }
    }

    if (filter) filter.addEventListener('input', function () { seite = 1; malen(); });

    // Auswahl: Zeilen-Checkboxen pflegen data-state=selected + Zähler; Kopf = alle.
    var alleBox = root.querySelector('[data-dt-select-all]');
    root.querySelectorAll('[data-dt-select]').forEach(function (box) {
      box.addEventListener('change', function () {
        var zeile = box.closest('tr');
        if (box.checked) zeile.dataset.state = 'selected';
        else delete zeile.dataset.state;
        if (alleBox) {
          alleBox.checked = alleZeilen.every(function (z) {
            var b = z.querySelector('[data-dt-select]');
            return b && b.checked;
          });
        }
        zaehlerMalen();
      });
    });
    if (alleBox) {
      alleBox.addEventListener('change', function () {
        alleZeilen.forEach(function (z) {
          var b = z.querySelector('[data-dt-select]');
          if (!b) return;
          b.checked = alleBox.checked;
          if (b.checked) z.dataset.state = 'selected';
          else delete z.dataset.state;
        });
        zaehlerMalen();
      });
    }

    // Rechtsklick-Menü kontextsensitiv (PO): auf einer MARKIERTEN Zeile zeigt es die
    // Sammel-Aktionen, auf einer nicht markierten das Einzel-Menü — entschieden im
    // Capture, bevor das Context Menu öffnet und misst.
    var cmZeile = root.querySelector('[data-dt-cm-row]');
    var cmBulk = root.querySelector('[data-dt-cm-bulk]');
    if (cmZeile && cmBulk) {
      root.addEventListener('contextmenu', function (e) {
        var zeile = e.target.closest('tbody tr');
        var box = zeile ? zeile.querySelector('[data-dt-select]') : null;
        var markiert = zeile ? (box ? box.checked : zeile.dataset.state === 'selected') : false;
        cmZeile.toggleAttribute('hidden', markiert);
        cmBulk.toggleAttribute('hidden', !markiert);
      }, true);
    }

    // Bulk-Toolbar „Abbrechen" (data-dt-clearselect): hebt die Auswahl komplett auf.
    root.querySelectorAll('[data-dt-clearselect]').forEach(function (knopf) {
      knopf.addEventListener('click', function () {
        alleZeilen.forEach(function (z) {
          var b = z.querySelector('[data-dt-select]');
          if (b) b.checked = false;
          delete z.dataset.state;
        });
        if (alleBox) alleBox.checked = false;
        zaehlerMalen();
      });
    });

    // Zeilenklick wählt aus (Standard, PO 21): Klick irgendwo auf der Zeile togglet die
    // Auswahl — Bedienelemente (Knöpfe, Links, die Checkbox selbst) bleiben unberührt.
    // Ohne Checkbox-Spalte (data-dt-rowselect an der Hülle) togglet data-state direkt.
    if (root.hasAttribute('data-dt-rowselect') || root.querySelector('[data-dt-select]')) {
      koerper.addEventListener('click', function (e) {
        if (e.target.closest('button, a, input, label, .dropdown-menu')) return;
        // Editier-Modus (data-edit-table): Klick in eine editierbare Zelle setzt den
        // Cursor — er darf nicht nebenbei die Zeilenauswahl togglen.
        if (e.target.closest('td[contenteditable]')) return;
        var zeile = e.target.closest('tr');
        if (!zeile || !koerper.contains(zeile)) return;
        var box = zeile.querySelector('[data-dt-select]');
        if (box) {
          box.checked = !box.checked;
          box.dispatchEvent(new Event('change', { bubbles: true }));
        } else if (root.hasAttribute('data-dt-rowselect')) {
          if (zeile.dataset.state === 'selected') delete zeile.dataset.state;
          else zeile.dataset.state = 'selected';
          zaehlerMalen();
        }
      });
    }

    // Spalten-Menü: menuitemcheckbox mit data-dt-col="<Spaltenindex ab 0>" blendet
    // th+td der Spalte aus. Listener auf dem Menü selbst (Capture) — wireMenuChecks
    // stoppt die Propagation dort, Listener am selben Element laufen aber weiter.
    root.querySelectorAll('[role="menu"]:has([data-dt-col])').forEach(function (menue) {
      menue.addEventListener('click', function (e) {
        var knopf = e.target.closest('[data-dt-col]');
        if (!knopf) return;
        var idx = parseInt(knopf.dataset.dtCol, 10);
        var an = knopf.getAttribute('aria-checked') !== 'false';
        tabelle.querySelectorAll('tr').forEach(function (zeile) {
          if (zeile.cells[idx]) zeile.cells[idx].hidden = !an;
        });
      }, true);
    });

    // Spaltenfilter: die Filter-Combobox meldet jede Änderung (auch Chip-X) über
    // 'c22-fc-change'; der Trichter-Trigger zeigt den aktiven Filter über
    // aria-pressed (Accent-Kanon).
    spaltenMenues.forEach(function (menue) {
      var panel = menue.closest('[data-filter-combo]') || menue;
      panel.addEventListener('c22-fc-change', function () {
        var huelle = menue.closest('.popover, .dropdown-menu');
        var t = huelle ? huelle.querySelector('button[aria-expanded]') : null;
        if (t) {
          var aktiv = spaltenFilter().some(function (f) {
            return f.idx === parseInt(menue.dataset.dtFilterCol, 10) && f.aktiv;
          });
          t.setAttribute('aria-pressed', aktiv ? 'true' : 'false');
        }
        seite = 1;
        malen();
      });
    });

    // Sortierung: Klick zykliert unsortiert -> aufsteigend -> absteigend -> unsortiert
    // („unsortiert" stellt die Ursprungsreihenfolge wieder her). Standard sortiert EINE
    // Spalte; mit data-dt-multisort an der Hülle bleiben vorige Sortierungen als
    // SEKUNDÄRE Schlüssel erhalten (zuletzt geklickt = primär). Icons werden per
    // Attribut umgeschaltet — `svg.hidden = …` wäre bei SVG nur eine Expando-Property
    // (hidden ist HTMLElement-IDL) und ließ die Pfeile stehen.
    var urOrdnung = alleZeilen.slice();
    var multi = root.hasAttribute('data-dt-multisort');
    var stapel = []; // {knopf, th, idx, art, richtung} — neueste zuerst (primär)
    function sortWert(zeile, idx, art) {
      var text = zeile.cells[idx].textContent.trim();
      if (art === 'number') return parseFloat(text.replace(/\./g, '').replace(',', '.')) || 0;
      if (art === 'date') {
        var t = text.split('.');
        return t.length === 3 ? t[2] + t[1] + t[0] : text;
      }
      return text.toLowerCase();
    }
    function sortMalen() {
      root.querySelectorAll('thead th[aria-sort]').forEach(function (t) { t.removeAttribute('aria-sort'); });
      root.querySelectorAll('[data-dt-sort]').forEach(function (k) {
        var eintrag = null;
        stapel.forEach(function (e) { if (e.knopf === k) eintrag = e; });
        if (eintrag) eintrag.th.setAttribute('aria-sort', eintrag.richtung);
        var zustand = eintrag ? (eintrag.richtung === 'ascending' ? 'asc' : 'desc') : 'none';
        k.querySelectorAll('[data-dt-icon]').forEach(function (svg) {
          svg.toggleAttribute('hidden', svg.dataset.dtIcon !== zustand);
        });
        // Mehrspalten-Rang (PO): sekundäre/tertiäre Sortierschlüssel tragen ²/³/⁴
        // hinter dem Pfeil — der primäre bleibt unmarkiert.
        var rang = k.querySelector('[data-dt-rang]');
        if (!rang) {
          rang = document.createElement('span');
          rang.setAttribute('data-dt-rang', '');
          rang.className = 'tabular-nums';
          k.appendChild(rang);
        }
        var pos = eintrag ? stapel.indexOf(eintrag) : -1;
        rang.textContent = pos > 0 ? ['²', '³', '⁴', '⁵'][pos - 1] || '' : '';
      });
    }
    function sortieren() {
      alleZeilen.sort(function (a, b) {
        for (var i = 0; i < stapel.length; i++) {
          var e = stapel[i];
          var x = sortWert(a, e.idx, e.art);
          var y = sortWert(b, e.idx, e.art);
          var v = x < y ? -1 : x > y ? 1 : 0;
          if (v) return e.richtung === 'ascending' ? v : -v;
        }
        return urOrdnung.indexOf(a) - urOrdnung.indexOf(b);
      });
      alleZeilen.forEach(function (z) { koerper.appendChild(z); });
      malen();
    }
    root.querySelectorAll('[data-dt-sort]').forEach(function (knopf) {
      var th = knopf.closest('th');
      // Vorbelegte Sortierung aus dem Markup (aria-sort am th) in den Stapel übernehmen.
      if (th.getAttribute('aria-sort')) {
        stapel.push({ knopf: knopf, th: th, idx: th.cellIndex, art: knopf.dataset.dtSort, richtung: th.getAttribute('aria-sort') });
      }
      knopf.addEventListener('click', function () {
        var eintrag = null;
        stapel.forEach(function (e) { if (e.knopf === knopf) eintrag = e; });
        if (!eintrag) {
          eintrag = { knopf: knopf, th: th, idx: th.cellIndex, art: knopf.dataset.dtSort, richtung: 'ascending' };
          if (multi) stapel.unshift(eintrag);
          else stapel = [eintrag];
        } else if (eintrag.richtung === 'ascending') {
          eintrag.richtung = 'descending';
          if (multi) {
            stapel.splice(stapel.indexOf(eintrag), 1);
            stapel.unshift(eintrag); // erneut geklickt = wieder primär
          }
        } else {
          stapel.splice(stapel.indexOf(eintrag), 1);
        }
        sortMalen();
        sortieren();
      });
    });

    // Sortieren aus dem Filter-Panel (PO 21: Sortieren-Submenü im Trichter):
    // data-dt-sortdir="ascending|descending|none" wirkt auf den Sortier-Knopf
    // des Spaltenkopfs, in dem das Panel steckt (fixed ist nur die CSS-Position,
    // im DOM bleibt es im th) — gesetzte Richtung wird primärer Schlüssel.
    root.querySelectorAll('[data-dt-sortdir]').forEach(function (knopf) {
      knopf.addEventListener('click', function () {
        var th = knopf.closest('th');
        var sortKnopf = th ? th.querySelector('[data-dt-sort]') : null;
        if (!sortKnopf) return;
        var richtung = knopf.dataset.dtSortdir;
        var eintrag = null;
        stapel.forEach(function (e) { if (e.knopf === sortKnopf) eintrag = e; });
        if (eintrag) stapel.splice(stapel.indexOf(eintrag), 1);
        if (richtung !== 'none') {
          eintrag = { knopf: sortKnopf, th: th, idx: th.cellIndex, art: sortKnopf.dataset.dtSort, richtung: richtung };
          if (multi) stapel.unshift(eintrag);
          else stapel = [eintrag];
        }
        sortMalen();
        sortieren();
      });
    });

    // Spalten-Panel im Filter-Combobox-Stil (PO 21a: Chips = sichtbare Spalten,
    // darunter die Liste): wireFilterCombo pflegt Chips/Auswahl und feuert
    // c22-fc-change — hier nur die Spalten der Tabelle nachziehen.
    root.querySelectorAll('[data-dt-colpanel]').forEach(function (panel) {
      panel.addEventListener('c22-fc-change', function () {
        panel.querySelectorAll("[role='option'][data-dt-col]").forEach(function (o) {
          var idx = parseInt(o.dataset.dtCol, 10);
          var an = o.getAttribute('aria-selected') === 'true';
          tabelle.querySelectorAll('tr').forEach(function (zeile) {
            if (zeile.cells[idx]) zeile.cells[idx].hidden = !an;
          });
        });
      });
    });

    // Zurücksetzen (data-dt-reset): leert Suchfeld, Spaltenfilter und Sortier-Stapel.
    // Kann mehrfach existieren (Toolbar-Icon + Menüzeile) — alle verdrahten.
    root.querySelectorAll('[data-dt-reset]').forEach(function (reset) {
      reset.addEventListener('click', function () {
        if (filter) filter.value = '';
        spaltenMenues.forEach(function (menue) {
          // Facetten-Semantik: zurücksetzen = kein Haken (= kein Filter).
          menue.querySelectorAll("[role='option']").forEach(function (o) {
            o.setAttribute('aria-selected', 'false');
            o.hidden = false;
          });
          var panel = menue.closest('[data-filter-combo]');
          var suche = panel ? panel.querySelector('input') : null;
          if (suche) suche.value = '';
          if (panel) panel.dispatchEvent(new CustomEvent('c22-fc-refresh'));
          var huelle = menue.closest('.popover, .dropdown-menu');
          var t = huelle ? huelle.querySelector('button[aria-expanded]') : null;
          if (t) t.setAttribute('aria-pressed', 'false');
        });
        stapel = [];
        seite = 1;
        sortMalen();
        sortieren();
      });
    });

    // Zeilen pro Seite: Basecoat-Select — Klick auf eine Option, danach den Wert
    // aus dem hidden-Input lesen (Basecoat aktualisiert ihn im selben Klick).
    if (groesseInput) {
      root.querySelectorAll('[data-dt-pagesize] [role="option"]').forEach(function (opt) {
        opt.addEventListener('click', function () {
          setTimeout(function () {
            proSeite = parseInt(groesseInput.value, 10) || proSeite;
            seite = 1;
            malen();
          }, 0);
        });
      });
    }
    // Zeilen pro Seite als Menü-Radios (Einstellungs-Menü, PO 21a): wireMenuChecks
    // pflegt die Radio-Exklusivität, stoppt aber die Capture-Propagation am Menü —
    // deshalb (wie bei data-dt-col) Capture-Listener am Menü statt am Knopf.
    root.querySelectorAll('[role="menu"]:has([data-dt-pagesize-opt])').forEach(function (menue) {
      menue.addEventListener('click', function (e) {
        var opt = e.target.closest('[data-dt-pagesize-opt]');
        if (!opt) return;
        setTimeout(function () {
          var wert = parseInt(opt.dataset.dtPagesizeOpt, 10);
          if (!isNaN(wert)) proSeite = wert; // 0 = „Alle anzeigen"
          seite = 1;
          malen();
        }, 0);
      }, true);
    });
    var vor = root.querySelector('[data-dt-prev]');
    var nach = root.querySelector('[data-dt-next]');
    if (vor) vor.addEventListener('click', function () { if (seite > 1) { seite--; malen(); } });
    if (nach) nach.addEventListener('click', function () { seite++; malen(); });

    malen();
    zaehlerMalen();
    // Höhe nach dem Font-Laden neu einfrieren (PO 21): die erste Messung läuft mit
    // Fallback-Font-Metriken — die Tabelle hatte anfangs unten Luft, die erst beim
    // nächsten malen() (z.B. Seitenwechsel) verschwand.
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(malen);
  }

  // Mehrgriff-Slider (Slider 53, data-slider-multi): gestapelte native Range-Inputs.
  // Klemmt jeden Griff an seine Nachbarn (kein Überkreuzen) und malt die Füllung
  // zwischen kleinstem und größtem Wert auf die Hülle (--von/--bis fürs ::before).
  function wireMultiSlider(box) {
    if (box.dataset.c22MultiWired) return;
    box.dataset.c22MultiWired = '1';
    var inputs = Array.prototype.slice.call(box.querySelectorAll("input[type='range']"));
    if (!inputs.length) return;
    function malen() {
      var min = parseFloat(inputs[0].min) || 0;
      var max = parseFloat(inputs[0].max) || 100;
      var werte = inputs.map(function (i) { return parseFloat(i.value); });
      var lo = Math.min.apply(null, werte);
      var hi = Math.max.apply(null, werte);
      box.style.setProperty('--von', ((lo - min) / (max - min)) * 100 + '%');
      box.style.setProperty('--bis', ((hi - min) / (max - min)) * 100 + '%');
    }
    inputs.forEach(function (inp, i) {
      inp.addEventListener('input', function () {
        var v = parseFloat(inp.value);
        if (i > 0) v = Math.max(v, parseFloat(inputs[i - 1].value));
        if (i < inputs.length - 1) v = Math.min(v, parseFloat(inputs[i + 1].value));
        if (v !== parseFloat(inp.value)) inp.value = v;
        malen();
      });
    });
    function wertAus(clientX) {
      var r = box.getBoundingClientRect();
      var min = parseFloat(inputs[0].min) || 0;
      var max = parseFloat(inputs[0].max) || 100;
      var step = parseFloat(inputs[0].step) || 1;
      var griff = 16; // --slider-thumb-size: der Griffmittelpunkt läuft nicht bis an die Kanten
      var p = (clientX - r.left - griff / 2) / (r.width - griff);
      p = Math.max(0, Math.min(1, p));
      if (getComputedStyle(box).direction === 'rtl') p = 1 - p;
      var v = min + p * (max - min);
      v = Math.round(v / step) * step;
      return Math.max(min, Math.min(max, v));
    }
    function naechster(ziel) {
      var inp = inputs[0];
      var dichtest = Infinity;
      inputs.forEach(function (i) {
        var d = Math.abs(parseFloat(i.value) - ziel);
        // Gleichstand (Griffe übereinander): in Klickrichtung liegender Griff gewinnt,
        // sonst klemmte er sofort am Nachbarn fest.
        if (d < dichtest || (d === dichtest && ziel > parseFloat(i.value))) {
          dichtest = d;
          inp = i;
        }
      });
      return inp;
    }
    // Hover-Ring wie beim einfachen Slider: die Hülle markiert den DICHTESTEN Griff
    // (data-hover -> Ring per CSS) — denselben, den ein Klick greifen würde. Direkt
    // auf dem Griff ringt der Input weiter nativ über den :hover-Kanon.
    function hoverMarkieren(inp) {
      inputs.forEach(function (i) {
        if (i !== inp) i.removeAttribute('data-hover');
      });
      if (inp) inp.setAttribute('data-hover', '');
    }
    box.addEventListener('pointermove', function (e) {
      if (e.buttons) return; // beim Ziehen hält die Capture-Logik den Griff
      hoverMarkieren(e.target === box ? naechster(wertAus(e.clientX)) : null);
    });
    box.addEventListener('pointerleave', function () { hoverMarkieren(null); });
    // Track-Klick (PO): springt den DICHTESTEN Griff an die Klickstelle und hält ihn,
    // solange gedrückt bleibt (Pointer-Capture auf der Hülle — die Inputs selbst sind
    // pointer-events-none, nur ihre Griffe fangen Events und ziehen dann nativ).
    box.addEventListener('pointerdown', function (e) {
      if (e.target !== box) return; // Griff getroffen -> natives Ziehen des Inputs
      e.preventDefault();
      var inp = naechster(wertAus(e.clientX));
      hoverMarkieren(inp);
      function setzen(clientX) {
        inp.value = wertAus(clientX);
        inp.dispatchEvent(new Event('input', { bubbles: true }));
      }
      setzen(e.clientX);
      inp.focus({ preventScroll: true });
      box.setPointerCapture(e.pointerId);
      function move(ev) { setzen(ev.clientX); }
      function up() {
        box.removeEventListener('pointermove', move);
        box.removeEventListener('pointerup', up);
        box.removeEventListener('pointercancel', up);
        inp.dispatchEvent(new Event('change', { bubbles: true }));
      }
      box.addEventListener('pointermove', move);
      box.addEventListener('pointerup', up);
      box.addEventListener('pointercancel', up);
    });
    malen();
  }

  // Stummschalter (Slider 53): data-mute-Knopf graut den Slider seiner Gruppe aus
  // (data-muted — opacity wie disabled, aber bedienbar) und tauscht das Lautsprecher-Icon;
  // Bedienen des Reglers (Klick/Ziehen) entstummt wieder.
  function wireMute(btn) {
    if (btn.dataset.c22MuteWired) return;
    btn.dataset.c22MuteWired = '1';
    var gruppe = btn.closest('[data-mute-group]');
    var regler = gruppe ? gruppe.querySelector("input[type='range']") : null;
    if (!regler) return;
    var svgs = btn.querySelectorAll('svg');
    function setzen(stumm) {
      btn.setAttribute('aria-pressed', stumm ? 'true' : 'false');
      if (stumm) regler.setAttribute('data-muted', 'true');
      else regler.removeAttribute('data-muted');
      if (svgs.length > 1) {
        // toggleAttribute statt .hidden: die IDL-Property existiert an SVG nicht
        // (wäre nur eine Expando, das Icon bliebe sichtbar).
        svgs[0].toggleAttribute('hidden', stumm);
        svgs[1].toggleAttribute('hidden', !stumm);
      }
    }
    btn.addEventListener('click', function () {
      setzen(btn.getAttribute('aria-pressed') !== 'true');
    });
    ['pointerdown', 'input'].forEach(function (ev) {
      regler.addEventListener(ev, function () {
        if (regler.hasAttribute('data-muted')) setzen(false);
      });
    });
  }

  // Feedback-Daumen (Message 39c): Gut/Schlecht als gegenseitig ausschließendes Paar —
  // Klick togglet aria-pressed (Accent-Look aus .btn[aria-pressed]), der jeweils andere
  // Daumen im selben Aktions-Container wird zurückgesetzt.
  function wireFeedback(btn) {
    if (btn.dataset.c22FbWired) return;
    btn.dataset.c22FbWired = '1';
    btn.addEventListener('click', function () {
      var an = btn.getAttribute('aria-pressed') !== 'true';
      var reihe = btn.closest('[data-message-actions]') || btn.parentElement;
      reihe.querySelectorAll('[data-feedback]').forEach(function (b) {
        b.setAttribute('aria-pressed', 'false');
      });
      btn.setAttribute('aria-pressed', an ? 'true' : 'false');
    });
  }

  // Checkbox-/Radio-Einträge in Menüs (PO 38c): ein Klick schaltet den Zustand um und lässt
  // das Menü OFFEN — Basecoats Dropdown schlösse es nach jedem Klick, was bei Mehrfach-
  // Auswahl (Symbolleisten an/aus) nervt. Capture-Phase am Menü: stopPropagation verhindert,
  // dass Basecoats Schließ-Handler (am Eintrag/Popover) den Klick überhaupt sieht.
  // Radio räumt seine Gruppe (role=group, sonst das ganze Menü); normale Einträge
  // schließen weiter wie gewohnt.
  function wireMenuChecks(menu) {
    if (menu.dataset.c22ChkWired) return;
    menu.dataset.c22ChkWired = '1';
    menu.addEventListener('click', function (e) {
      var item = e.target.closest("[role='menuitemcheckbox'], [role='menuitemradio']");
      if (!item || !menu.contains(item)) return;
      e.stopPropagation();
      if (item.getAttribute('role') === 'menuitemradio') {
        var kreis = item.closest("[role='group']") || menu;
        kreis.querySelectorAll("[role='menuitemradio']").forEach(function (r) {
          r.setAttribute('aria-checked', 'false');
        });
        item.setAttribute('aria-checked', 'true');
      } else {
        item.setAttribute('aria-checked', item.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
      }
      // stopPropagation frisst Inline-Handler auf den Items — wer auf die Auswahl
      // reagieren will (z.B. Trigger-Text nachziehen), hört auf dieses Event.
      menu.dispatchEvent(new CustomEvent('c22-menu-check', { detail: { item: item }, bubbles: true }));
    }, true);
  }

  // Pagination ([data-pagination] am nav/div) — macht die Demo-Bauformen funktional (PO 43):
  // Zahl-Listen laufen über die STANDARD-FENSTERLOGIK [1] … [i-1] [i] [i+1] … [n]
  // (nie mehr als 7 Einträge; Zahl- und Ellipsen-LIs werden je Stand aus den Vorlagen
  // des Markups neu erzeugt). Punkte ([data-page-dot]) wechseln die Seite, Richtungs-/
  // Sprungknöpfe werden an ihren Icons erkannt (chevron-left/right = ±1,
  // chevrons-left/right = Anfang/Ende), Zahlenfeld und „Seite X von Y"-Zähler werden
  // mitgepflegt (Eingabe klemmt auf 1…max). Randverhalten an BEIDEN Enden: Knöpfe
  // werden deaktiviert (Links per aria-disabled — können kein disabled tragen), ein
  // anfangs unsichtbarer Knopf (.invisible) wird aus-/eingeblendet, Platz bleibt.
  function wirePagination(root) {
    if (root.dataset.c22PgWired) return;
    root.dataset.c22PgWired = '1';
    var eingabe = root.querySelector("input[type='number']");
    var punkte = Array.prototype.slice.call(root.querySelectorAll('[data-page-dot]'));
    var alleBtn = Array.prototype.slice.call(root.querySelectorAll('.btn'));
    var zahlKnoepfe = alleBtn.filter(function (b) { return /^\d+$/.test(b.textContent.trim()); });
    var zaehler = null;
    Array.prototype.forEach.call(root.querySelectorAll('span'), function (s) {
      if (!zaehler && /^Seite\s+\d+\s+von\s+\d+$/.test(s.textContent.trim().replace(/\s+/g, ' '))) zaehler = s;
    });
    var gesamt = 1;
    if (eingabe) gesamt = parseInt(eingabe.max, 10) || 1;
    else if (punkte.length) gesamt = punkte.length;
    else if (zaehler) gesamt = parseInt(/von\s+(\d+)/.exec(zaehler.textContent)[1], 10);
    else if (zahlKnoepfe.length) gesamt = Math.max.apply(null, zahlKnoepfe.map(function (b) { return parseInt(b.textContent, 10); }));
    var akt = 1;
    var aktEl = root.querySelector("[aria-current='page']");
    if (eingabe) akt = parseInt(eingabe.value, 10) || 1;
    else if (aktEl && /^\d+$/.test(aktEl.textContent.trim())) akt = parseInt(aktEl.textContent, 10);
    else if (aktEl && punkte.length) akt = punkte.indexOf(aktEl) + 1;
    else if (zaehler) akt = parseInt(/Seite\s+(\d+)/.exec(zaehler.textContent)[1], 10);

    // Fenster-Modus (Zahl-Liste): Vorlagen sichern, Original-LIs raus — male() erzeugt neu
    var fenster = zahlKnoepfe.length > 1;
    var liste = null, naechsteLi = null, zahlTpl = null, ellipseTpl = null;
    if (fenster) {
      var ersteLi = zahlKnoepfe[0].closest('li');
      liste = ersteLi.parentElement;
      zahlTpl = ersteLi.cloneNode(true);
      zahlTpl.querySelector('.btn').removeAttribute('aria-current');
      zahlTpl.querySelector('.btn').setAttribute('data-variant', 'ghost');
      Array.prototype.slice.call(liste.children).forEach(function (li) {
        var istEllipse = li.hasAttribute('data-pg-ellipsis');
        var b = li.querySelector('.btn');
        if (istEllipse && !ellipseTpl) ellipseTpl = li.cloneNode(true);
        if (istEllipse || (b && /^\d+$/.test(b.textContent.trim()))) li.remove();
      });
      Array.prototype.forEach.call(liste.querySelectorAll(".btn svg[data-icon-lu='chevron-right'], .btn svg[data-icon-lu='chevrons-right']"), function (ic) {
        if (!naechsteLi) naechsteLi = ic.closest('li');
      });
    }
    // IMMER 7 Elemente (PO): bis Seite 4 → 1 2 3 4 5 … n, ab n-3 gespiegelt
    // → 1 … n-4 n-3 n-2 n-1 n, dazwischen → 1 … i-1 i i+1 … n. Bei n ≤ 7 alle.
    function fensterSeiten() {
      var a = [], i;
      if (gesamt <= 7) { for (i = 1; i <= gesamt; i++) a.push(i); return a; }
      if (akt <= 4) return [1, 2, 3, 4, 5, 0, gesamt];   // 0 = Ellipse
      if (akt >= gesamt - 3) return [1, 0, gesamt - 4, gesamt - 3, gesamt - 2, gesamt - 1, gesamt];
      return [1, 0, akt - 1, akt, akt + 1, 0, gesamt];
    }
    var randKnoepfe = [];
    function male() {
      if (fenster) {
        Array.prototype.slice.call(liste.querySelectorAll('[data-pg-gen]')).forEach(function (li) { li.remove(); });
        fensterSeiten().forEach(function (s) {
          var li;
          if (s === 0) {
            li = ellipseTpl.cloneNode(true);
          } else {
            li = zahlTpl.cloneNode(true);
            var b = li.querySelector('.btn');
            b.textContent = s;
            b.setAttribute('data-variant', s === akt ? 'outline' : 'ghost');
            if (s === akt) b.setAttribute('aria-current', 'page');
            b.addEventListener('click', function (e) { e.preventDefault(); setze(s); });
          }
          li.setAttribute('data-pg-gen', '1');
          liste.insertBefore(li, naechsteLi);
        });
      }
      punkte.forEach(function (d, i) {
        if (i + 1 === akt) d.setAttribute('aria-current', 'page'); else d.removeAttribute('aria-current');
      });
      if (eingabe) eingabe.value = akt;
      if (zaehler) zaehler.textContent = zaehler.textContent.replace(/Seite\s+\d+/, 'Seite ' + akt);
      randKnoepfe.forEach(function (k) {
        var amRand = k.richtung < 0 ? akt <= 1 : akt >= gesamt;
        if (k.modus === 'hide') k.el.classList.toggle('invisible', amRand);
        else if (k.el.tagName === 'BUTTON') { k.el.disabled = amRand; k.el.setAttribute('aria-disabled', amRand ? 'true' : 'false'); }
        else if (amRand) { k.el.setAttribute('aria-disabled', 'true'); k.el.setAttribute('tabindex', '-1'); }
        else { k.el.removeAttribute('aria-disabled'); k.el.removeAttribute('tabindex'); }
      });
    }
    function setze(n) {
      akt = Math.min(Math.max(n, 1), gesamt);
      male();
    }
    alleBtn.forEach(function (b) {
      if (/^\d+$/.test(b.textContent.trim())) return;   // Zahl-Knöpfe erzeugt male() neu
      var ic = b.querySelector('svg[data-icon-lu]');
      var name = ic && ic.getAttribute('data-icon-lu');
      var f = null, richtung = 0;
      if (name === 'chevron-left') { f = function () { setze(akt - 1); }; richtung = -1; }
      else if (name === 'chevron-right') { f = function () { setze(akt + 1); }; richtung = 1; }
      else if (name === 'chevrons-left') { f = function () { setze(1); }; richtung = -1; }
      else if (name === 'chevrons-right') { f = function () { setze(gesamt); }; richtung = 1; }
      if (!f) return;
      randKnoepfe.push({ el: b, richtung: richtung, modus: b.classList.contains('invisible') ? 'hide' : 'disable' });
      b.addEventListener('click', function (e) { e.preventDefault(); f(); });
    });
    punkte.forEach(function (d, i) {
      d.addEventListener('click', function () { setze(i + 1); });
    });
    if (eingabe) eingabe.addEventListener('change', function () {
      setze(parseInt(eingabe.value, 10) || akt);
    });
    male();   // Anfangszustand normalisieren: Fenster erzeugen, Ränder ausgrauen
  }

  // <input data-date-input aria-controls="panel-id"> — Datums-Eingabe mit Kalender-Popover:
  // Fokus/Klick öffnet, Klick außerhalb/Escape schließt (eigene Verdrahtung — Basecoats Popover
  // akzeptiert nur <button> als Trigger). Tippen übernimmt das Datum live in den Kalender und
  // vervollständigt UNSICHTBAR aus der aktuellen Auswahl (Basis; anfangs data-selected/-month):
  // „12" → Tag 12 im Basis-Monat/-Jahr, „1204"/„12.4" → 12. April im Basis-Jahr, dazu die
  // vollen Formen tt.mm.jjjj, tt.mm.jj, ttmmjjjj, ttmmjj. Zweistelliges Jahr: > aktuelles
  // jj → 19xx (Geburtsdaten), sonst 20xx. Kalender-Klick schreibt zurück ins Feld.
  function wireDateInput(inp) {
    if (inp.dataset.c22DiWired) return;
    inp.dataset.c22DiWired = '1';
    var panel = document.getElementById(inp.getAttribute('aria-controls') || '');
    if (!panel) return;
    var cal = panel.querySelector('[data-calendar]');
    var now = new Date();
    var base = calKey(now.getFullYear(), now.getMonth(), now.getDate());
    if (cal && cal.dataset.selected) base = calNorm(cal.dataset.selected);
    else if (cal && cal.dataset.month) base = calNorm(cal.dataset.month + '-01');

    function open() { panel.setAttribute('aria-hidden', 'false'); inp.setAttribute('aria-expanded', 'true'); }
    function close() { panel.setAttribute('aria-hidden', 'true'); inp.setAttribute('aria-expanded', 'false'); }
    inp.addEventListener('focus', open);
    inp.addEventListener('click', open);        // bewusst kein Toggle: Klick ins aktive Feld hält offen
    inp.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    // Die Hülle (z.B. .relative mit Kalender-Icon) zählt als Feldfläche: Klick darauf öffnet
    // (fokussiert), statt als Außenklick zu schließen (PO 31a — Icon klickbar).
    var huelle = inp.parentElement;
    huelle.addEventListener('click', function (e) {
      if (e.target !== inp && !panel.contains(e.target)) inp.focus();
    });
    document.addEventListener('click', function (e) {
      if (e.target !== inp && !panel.contains(e.target) && !huelle.contains(e.target)) close();
    });

    function parse(txt) {
      var t = txt.trim(), d = null, m = null, y = null;
      if (!/^[\d.]+$/.test(t)) return null;
      if (t.indexOf('.') >= 0) {
        var p = t.split('.');
        if (p.length > 3 || !p[0] || p[0].length > 2 || (p[1] || '').length > 2) return null;
        d = +p[0];
        if (p[1]) m = +p[1];
        if (p.length === 3 && p[2]) { if (!/^(\d{2}|\d{4})$/.test(p[2])) return null; y = p[2]; }
      } else {
        if (t.length <= 2) { d = +t; }
        else if (t.length <= 4) { d = +t.slice(0, 2); m = +t.slice(2); }
        else if (t.length === 6 || t.length === 8) { d = +t.slice(0, 2); m = +t.slice(2, 4); y = t.slice(4); }
        else return null;   // 5/7 Ziffern sind mehrdeutig
      }
      var bp = base.split('-');
      if (m === null) m = +bp[1];
      if (y === null) y = +bp[0];
      else if (String(y).length === 2) { var jj = +y; y = jj > new Date().getFullYear() % 100 ? 1900 + jj : 2000 + jj; }
      else y = +y;
      if (m < 1 || m > 12 || d < 1 || d > new Date(y, m, 0).getDate()) return null;
      return y + '-' + calPad(m) + '-' + calPad(d);
    }
    inp.addEventListener('input', function () {
      // Nur Ziffern und Punkte zulassen; bei reiner Ziffernfolge die Punkte automatisch
      // setzen (1204 -> 12.04, 150788 -> 15.07.88) — analog zum ':' im Uhr-Input.
      var v = inp.value.replace(/[^\d.]/g, '');
      if (/^\d+$/.test(v)) {
        if (v.length > 4) v = v.slice(0, 2) + '.' + v.slice(2, 4) + '.' + v.slice(4);
        else if (v.length > 2) v = v.slice(0, 2) + '.' + v.slice(2);
      }
      if (v !== inp.value) inp.value = v;
      var key = parse(v);
      if (key && cal) {
        base = key;   // die Vervollständigung folgt der zuletzt verstandenen Auswahl
        cal.dispatchEvent(new CustomEvent('c22:calendar-set', { detail: { selected: key } }));
      }
    });
    inp.addEventListener('blur', function () {
      if (!inp.value.trim()) return;
      var key = parse(inp.value);
      if (key) { var p = key.split('-'); inp.value = p[2] + '.' + p[1] + '.' + p[0]; }
    });
    if (cal) cal.addEventListener('c22:calendar-change', function (e) {
      if (!e.detail.selected) { inp.value = ''; return; }   // „Löschen" leert das Feld, bleibt offen
      base = e.detail.selected;
      var p = e.detail.selected.split('-');
      inp.value = p[2] + '.' + p[1] + '.' + p[0];
      close();   // Datumswahl schließt den Kalender (PO); „Heute"/Blättern feuern kein change
    });
  }

  // ---- Carousel (Basecoat hat keins) ----------------------------------------
  // Aufbauend auf nativem Snap-Scrolling (funktioniert auch ohne JS per Wisch/Trackpad/
  // Pfeiltasten). c22.js macht zusätzlich Prev/Next-Buttons + Punkt-Navigation funktional,
  // markiert JEDE sichtbare Folie (Einzel- wie Mehrfachansicht), pflegt einen "x von y"-Zähler,
  // den Endzustand (Button am Rand deaktiviert) und optionales Autoplay.
  // Markup:  <div data-carousel[="vertical"] [data-carousel-autoplay="4000"] class="relative …">
  //            <div data-carousel-viewport class="… snap-x/​snap-y overflow-…-auto">…Folien…</div>
  //            <button data-carousel-prev …>  <button data-carousel-next …>
  //            <a|button data-carousel-dot …> …          (optional, eine je Folie)
  //            <span data-carousel-counter></span>       (optional, füllt sich mit "x von y")
  //          </div>
  function wireCarousel(root) {
    if (root.dataset.c22CarWired) return;
    root.dataset.c22CarWired = '1';
    var vertical = root.dataset.carousel === 'vertical';
    var autoplay = +root.dataset.carouselAutoplay || 0;
    var loop = root.hasAttribute('data-carousel-loop'); // Endlos: an den Rändern zum anderen Ende springen
    var vp = root.querySelector('[data-carousel-viewport]');
    if (!vp) return;
    var slides = [].slice.call(vp.children);
    var prev = root.querySelector('[data-carousel-prev]');
    var next = root.querySelector('[data-carousel-next]');
    var dots = [].slice.call(root.querySelectorAll('[data-carousel-dot]'));
    var counter = root.querySelector('[data-carousel-counter]');

    // Schrittweite = Abstand zweier Folien (deckt gap UND Innen-padding ab); sonst Viewport-Maß.
    function step() {
      if (slides.length > 1) {
        return vertical ? slides[1].offsetTop - slides[0].offsetTop
                        : slides[1].offsetLeft - slides[0].offsetLeft;
      }
      return vertical ? vp.clientHeight : vp.clientWidth;
    }
    function maxScroll() { return vertical ? vp.scrollHeight - vp.clientHeight : vp.scrollWidth - vp.clientWidth; }
    function curPos() { return vertical ? vp.scrollTop : vp.scrollLeft; }
    function atEnd() { return (target != null ? target : curPos()) >= maxScroll() - 1; }
    function atStart() { return (target != null ? target : curPos()) <= 1; }
    function setEnds(pos) {
      // Endlos-Modus: die Pfeile bleiben immer bedienbar (am Rand wird gesprungen statt gesperrt).
      if (loop) { if (prev) prev.disabled = false; if (next) next.disabled = false; return; }
      if (prev) prev.disabled = pos <= 1;
      if (next) next.disabled = pos >= maxScroll() - 1;
    }

    // `target` = zuletzt per Button/Punkt beabsichtigte Zielposition. Solange sie gesetzt ist,
    // richtet sich der Endzustand danach — so wird der Rand-Button SOFORT beim Klick grau (die
    // smooth-Animation läuft noch) und flackert währenddessen nicht zurück; aufeinanderfolgende
    // Klicks addieren sich korrekt (Ist-Position hinkt sonst hinterher). `programmatic` markiert das
    // Zeitfenster unserer eigenen Scrolls; ein Scroll außerhalb davon = der Nutzer hat selbst
    // gewischt -> Ziel loslassen, damit wieder die Ist-Position zählt. Nur der Viewport scrollt
    // (kein Seiten-Sprung wie bei einem blanken #anker).
    var target = null, programmatic = 0, ticking = false;
    function scrollToPos(pos) {
      pos = Math.max(0, Math.min(maxScroll(), pos));
      target = pos; programmatic = Date.now() + 700;
      vp.scrollTo(vertical ? { top: pos, behavior: 'smooth' } : { left: pos, behavior: 'smooth' });
      setEnds(pos);
    }
    function go(sign) { scrollToPos((target != null ? target : curPos()) + sign * step()); }
    function goToSlide(i) {
      var vr = vp.getBoundingClientRect(), r = slides[i].getBoundingClientRect();
      scrollToPos(curPos() + (vertical ? r.top - vr.top : r.left - vr.left));
    }

    // Sichtbarer Anteil jeder Folie -> markiert werden ALLE hinreichend sichtbaren (>60 %).
    // Bei 1-je-Ansicht ist das genau eine, bei 3-je-Ansicht drei — dieselbe Logik.
    function update() {
      var vr = vp.getBoundingClientRect(), firstVisible = -1;
      slides.forEach(function (sl, di) {
        var r = sl.getBoundingClientRect();
        var vis = vertical
          ? (Math.min(r.bottom, vr.bottom) - Math.max(r.top, vr.top)) / (r.height || 1)
          : (Math.min(r.right, vr.right) - Math.max(r.left, vr.left)) / (r.width || 1);
        var on = vis > 0.6;
        if (on && firstVisible < 0) firstVisible = di;
        if (dots[di]) dots[di].setAttribute('aria-current', on ? 'true' : 'false');
      });
      if (firstVisible < 0) firstVisible = 0;
      if (counter) counter.textContent = (firstVisible + 1) + ' von ' + slides.length;
      setEnds(target != null ? target : curPos());
    }

    if (prev) prev.addEventListener('click', function () { if (loop && atStart()) scrollToPos(maxScroll()); else go(-1); });
    if (next) next.addEventListener('click', function () { if (loop && atEnd()) scrollToPos(0); else go(1); });
    dots.forEach(function (dot, di) {
      dot.addEventListener('click', function (e) { e.preventDefault(); goToSlide(di); });
    });

    vp.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        ticking = false;
        if (Date.now() > programmatic) target = null;   // Nutzer hat selbst gewischt -> Ziel los
        update();
      });
    });
    update();

    // Autoplay: eine Folie weiter, am Ende zurück auf Anfang (Endlosschleife). Pausiert, solange
    // der Zeiger auf dem Carousel liegt, damit man in Ruhe schauen/bedienen kann.
    // Tickt außerdem NUR, wenn das Carousel wirklich zu sehen ist: außerhalb des Viewports
    // (IntersectionObserver) und hinter einem modalen Dialog wird ausgesetzt. Sonst feuert das
    // programmatische Smooth-Scrolling (Main-Thread-Animation!) alle paar Sekunden auf einer
    // langen Seite ins Leere und lässt sichtbare Scroller ruckeln (Fund 2026-07-18, Dialog #23b).
    if (autoplay > 0) {
      var timer = null, visible = true;
      function tick() {
        if (!visible || document.querySelector('dialog[open]')) return;
        atEnd() ? goToSlide(0) : go(1);
      }
      function play() { if (!timer) timer = setInterval(tick, autoplay); }
      function stop() { clearInterval(timer); timer = null; }
      root.addEventListener('pointerenter', stop);
      root.addEventListener('pointerleave', play);
      if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (entries) {
          visible = entries[0].isIntersecting;
        }, { threshold: 0.1 }).observe(root);
      }
      play();
    }
  }

  // ---- Charts (datengetrieben, SVG) -----------------------------------------
  // Basecoat-Charts nutzen Chart.js auf <canvas> (nicht vendored); shadcn/Recharts nutzt SVG.
  // C22 geht den SVG-Weg: jedes Element ist ein DOM-Knoten -> Highlight/Hover/Tokens/a11y ohne
  // Neuzeichnen. Aus EINER Config (Daten-Array) kommen Skala, Achse, Formen, Legende UND Tooltip
  // -> eine Quelle der Wahrheit (SPOT), keine handberechneten Koordinaten.
  // Markup:  <div data-chart='{ "type":"bar", "labels":["Jan",…],
  //            "series":[{"name":"Besuche","data":[…],"color":"chart-1"}],
  //            "axis":true, "grid":true, "legend":false, "area":false, "max":1000, "unit":"" }'></div>
  // type: bar | bars | stacked | line | lines | step | smooth | pie | donut | radial | radar
  //   pie/donut   Kreis (chartPie) — EINE Geometrie, "inner" ist das Loch (0 = volle Torte)
  //   radial      Radialbalken (chartRadial) — je Kategorie ein konzentrischer Bogen auf einer Spur
  //   radar       Netzdiagramm (chartRadar)
  // Tooltip-Ausführungen (alle Typen, Vorbild shadcn-Reiter „Tooltips"):
  //   tipIndicator "dot" (Standard) | "line" | "none"   ·   tipLabel:false = ohne Titelzeile
  //   tipTitle "…" = eigener Titel   ·   tipUnit "kcal" = gedämpfte Einheit hinter dem Wert
  //   tipTotal:true = Summenzeile im Fuß (tipTotalLabel); das „Ganze" ist je Geometrie ein anderes
  //   — kartesisch die Kategorie über alle Serien, beim Kreis der Ring, beim Radial Band/Ringe
  //   ·   Serie mit "icon":"<phosphor>" = Icon
  //   statt Farbfleck   ·   tipPin:<index> = Tooltip dauerhaft sichtbar (Galerie/Doku zeigen ihn
  //   ohne Zeiger; die Platzierung zieht per ResizeObserver nach, sobald das Element Maße hat —
  //   in einem noch verborgenen Reiter-Panel wäre sie sonst 0).
  // SVG-Teile werden mit inline var(--token) gefärbt (NICHT mit Tailwind-Utilities) — Tailwind
  // scannt Quellen, JS-generierte Klassen kämen nicht in den Build. Der Tooltip wird in ECHTEN
  // Pixeln (getBoundingClientRect) gesetzt -> skalierungsunabhängig/responsiv.
  var CH_W = 320, CH_H = 180;
  function chCol(c, i) { return 'var(--' + (c || ('chart-' + ((i % 5) + 1))) + ')'; }
  function chNum(n) { return Number(n).toLocaleString('de-DE'); }
  function chNiceMax(v) {
    if (v <= 0) return 1;
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    var f = v / mag;
    var s = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
    return s * mag;
  }
  function chText(x, y, str, anchor, size, color) {
    return '<text x="' + x + '" y="' + y + '" text-anchor="' + anchor + '" fill="' + chCol(color || 'muted-foreground', 0) +
      '" font-size="' + size + '" style="font-variant-numeric:tabular-nums">' + calEsc(str) + '</text>';
  }
  // Catmull-Rom -> kubische Bézier (weiche Kurve durch alle Punkte).
  function chSmooth(p) {
    var d = 'M' + p[0][0].toFixed(1) + ',' + p[0][1].toFixed(1);
    for (var i = 0; i < p.length - 1; i++) {
      var p0 = p[i - 1] || p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] || p[i + 1];
      var c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      var c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += 'C' + c1x.toFixed(1) + ',' + c1y.toFixed(1) + ' ' + c2x.toFixed(1) + ',' + c2y.toFixed(1) + ' ' + p2[0].toFixed(1) + ',' + p2[1].toFixed(1);
    }
    return d;
  }
  function chTooltip(root) {
    var tip = document.createElement('div');
    tip.className = 'chart-tooltip';
    // WICHTIG: .chart-tooltip (Basecoat) setzt eine eigene CSS-translate-Property (-50% X / 8px Y),
    // die sich zu unserem transform ADDIEREN würde -> alles wandert nach links. Mit translate:none
    // ausschalten, dann steuert allein unser transform die Ausrichtung. Ebenso position:absolute
    // (Klasse ist fixed) -> wir positionieren relativ zum root.
    tip.style.cssText = 'position:absolute;left:0;top:0;opacity:0;pointer-events:none;translate:none;transform:translate(-50%,-100%);transition:opacity .12s;z-index:20';
    root.appendChild(tip);
    return tip;
  }
  // Tooltip-Inhalt. Der Marker links ist die einzige Stelle mit drei Ausführungen: Farbfleck
  // (Standard), schmaler Strich (tipIndicator "line") oder gar keiner ("none") — das Aussehen
  // dazu liegt in components.css, hier steht nur die Entscheidung. Ein Icon in der Zeile
  // (Serie mit "icon") ersetzt den Marker.
  function chTipHtml(title, rows, cfg, total) {
    cfg = cfg || {};
    var ind = cfg.tipIndicator || 'dot';
    var kopf = cfg.tipLabel === false ? ''
      : '<div class="chart-tooltip-title">' + calEsc(cfg.tipTitle != null ? cfg.tipTitle : title) + '</div>';
    function wert(v, suffix) {
      return '<span class="chart-tooltip-value">' + calEsc(v) +
        (suffix ? '<span class="chart-tooltip-unit">' + calEsc(suffix) + '</span>' : '') + '</span>';
    }
    var items = rows.map(function (r) {
      var marke = '';
      if (r.icon) marke = '<span class="chart-tooltip-icon" style="color:' + r.color + '">' + phIcon(r.icon) + '</span>';
      else if (ind !== 'none') marke = '<span class="chart-tooltip-indicator"' + (ind === 'line' ? ' data-variant="line"' : '') +
        ' style="--chart-indicator-color:' + r.color + '"></span>';
      return '<div class="chart-tooltip-item">' + marke +
        '<span class="chart-tooltip-label">' + calEsc(r.label) + '</span>' + wert(r.value, r.suffix) + '</div>';
    }).join('');
    var fuss = total
      ? '<div class="chart-tooltip-total"><span class="chart-tooltip-label">' + calEsc(total.label) + '</span>' +
        wert(total.value, total.suffix) + '</div>'
      : '';
    return kopf + '<div class="chart-tooltip-items">' + items + '</div>' + fuss;
  }
  // Summenzeile (tipTotal) aus einer fertigen Summe — EINE Stelle für alle Typen. Die runden
  // Charts zeigen je Zeiger nur EINEN Wert; ihre Summe ist deshalb nicht „über die Serien",
  // sondern die des Rings bzw. des Stapels (das Ganze, auf das sich der Anteil bezieht). Ohne
  // diesen gemeinsamen Bauer taten tipTotal/tipTotalLabel auf pie/donut/radial still nichts.
  function chTotalVon(cfg, summe) {
    if (!cfg.tipTotal) return null;
    return {
      label: cfg.tipTotalLabel || 'Gesamt',
      value: chNum(summe) + (cfg.unit || ''),
      suffix: cfg.tipUnit,
    };
  }
  // Summenzeile kartesischer Charts — die Werte einer Kategorie über alle Serien addiert.
  function chTotal(cfg, series, i) {
    return chTotalVon(cfg, series.reduce(function (a, se) { return a + (se.data[i] || 0); }, 0));
  }
  // Tooltip in echten Pixeln über einem SVG-Punkt (viewBox-Koordinaten) platzieren.
  function chPlace(tip, svgEl, root, vx, vy, vbW, vbH) {
    var sr = svgEl.getBoundingClientRect(), rr = root.getBoundingClientRect();
    tip.style.left = (sr.left - rr.left + vx / vbW * sr.width) + 'px';
    tip.style.top = (sr.top - rr.top + vy / vbH * sr.height - 10) + 'px';
    tip.style.opacity = '1';
  }
  // Tortenstück (Keil vom Mittelpunkt bis Radius r über den Winkelbereich a0..a1) — als volle,
  // transparente Trefferfläche für runde Charts, damit die Maus sauber je Segment/Achse zählt.
  function chWedge(cx, cy, r, a0, a1) {
    var x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    var x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    var large = (a1 - a0) > Math.PI ? 1 : 0;
    return 'M' + cx + ',' + cy + 'L' + x0.toFixed(1) + ',' + y0.toFixed(1) +
      'A' + r + ' ' + r + ' 0 ' + large + ' 1 ' + x1.toFixed(1) + ',' + y1.toFixed(1) + 'Z';
  }
  // Runde Charts: Tooltip radial (Richtung angle) ab dem Basispunkt (baseX,baseY in viewBox) nach außen
  // setzen, so dass sein EUKLIDISCH nächster Punkt konstanten Abstand (extraR + gap) zum Basispunkt hält.
  // Die Referenz ist ein Kreis mit Radius extraR um den Basispunkt — das deckt beide Geometrien mit einer
  // Formel ab:
  //   Donut  = durchgehender Ring: base = Kreismittelpunkt, extraR = Ringradius -> Abstand zur Ringkurve
  //            konstant (kürzeste Distanz, überall gleicher Spalt zum Ring).
  //   Radar  = diskreter Vertex:   base = Vertex, extraR = 0 -> Abstand direkt zum Punkt konstant.
  // Nur so ist es oben wie unten gleich; das Radar-Polygon ist nicht vertikal zentriert, also darf hier
  // NICHT gegen den Mittelpunkt gerechnet werden. Abstand wächst monoton mit dem Vorschub t -> Bisektion.
  function chPlaceRadial(tip, svgEl, root, baseX, baseY, angle, vbW, extraR) {
    var sr = svgEl.getBoundingClientRect(), rr = root.getBoundingClientRect();
    var scale = sr.width / vbW;                        // uniform (svg behält viewBox-Seitenverhältnis)
    var dx = Math.cos(angle), dy = Math.sin(angle);
    tip.style.transform = 'translate(-50%,-50%)';
    var w = tip.offsetWidth, h = tip.offsetHeight, target = (extraR || 0) * scale + 10;   // +10px Spalt
    function nearest(t) {                              // Abstand Basispunkt -> nächster Rechteckpunkt (Mitte bei base + t*dir)
      var ncx = dx * t, ncy = dy * t;
      var nx = Math.max(ncx - w / 2, Math.min(0, ncx + w / 2));
      var ny = Math.max(ncy - h / 2, Math.min(0, ncy + h / 2));
      return Math.sqrt(nx * nx + ny * ny);
    }
    var lo = 0, hi = target + Math.max(w, h);
    for (var k = 0; k < 32; k++) { var mid = (lo + hi) / 2; if (nearest(mid) < target) lo = mid; else hi = mid; }
    tip.style.left = (sr.left - rr.left + baseX * scale + dx * hi) + 'px';
    tip.style.top = (sr.top - rr.top + baseY * scale + dy * hi) + 'px';
    tip.style.opacity = '1';
  }
  function chLegItem(label, color) {
    return '<li><span class="chart-legend-item"><span class="chart-legend-indicator" style="--chart-indicator-color:' + color +
      '"></span><span>' + calEsc(label) + '</span></span></li>';
  }
  function chLegend(cfg) {
    if (!cfg.legend) return '';
    var items;
    // Runde Charts beschriften die KATEGORIEN (eine Serie, viele Farben), kartesische die SERIEN.
    if (cfg.type === 'donut' || cfg.type === 'pie' || cfg.type === 'radial') {
      items = (cfg.labels || []).map(function (l, i) { return chLegItem(l, chCol(((cfg.series[0] || {}).colors || [])[i], i)); });
    } else {
      items = (cfg.series || []).map(function (se, i) { return chLegItem(se.name || '', chCol(se.color, i)); });
    }
    return '<ul class="chart-legend" style="margin-top:12px">' + items.join('') + '</ul>';
  }
  // Serien -> Tooltip-Zeilen (Farbe/Name/Wert+Einheit); geteilt von kartesischen Charts und Radar.
  function chRows(series, i, unit, cfg) {
    return series.map(function (se, si) {
      return {
        color: chCol(se.color, si),
        label: se.name || '',
        value: chNum(se.data[i] || 0) + (unit || ''),
        suffix: cfg && cfg.tipUnit,
        icon: se.icon,
      };
    });
  }
  // Skalen-Maximum aus allen Serienwerten (schön gerundet), oder cfg.max wenn gesetzt.
  function chSeriesMax(cfg, series) {
    return cfg.max || chNiceMax(Math.max.apply(null, series.map(function (se) { return Math.max.apply(null, se.data); })) || 1);
  }
  // SVG + Legende in root setzen, Tooltip anlegen; root wird relativ (Tooltip liegt absolut darüber).
  function chMount(root, cfg, svg) {
    root.style.position = 'relative';
    root.innerHTML = svg + chLegend(cfg);
    return { svgEl: root.querySelector('svg'), tip: chTooltip(root) };
  }
  // Hover verdrahten: pointerenter je [data-hit] -> show(i), Zeiger verlässt das SVG -> hide().
  // cfg.tipPin heftet den Tooltip an einen Index: er ist ohne Zeiger sichtbar und kehrt nach dem
  // Hover dorthin zurück. Platziert wird per ResizeObserver statt einmalig — ein Chart in einem
  // noch verborgenen Reiter-Panel hat Maße 0, und chPlace rechnet in echten Pixeln; sobald das
  // Panel aufgeht, meldet der Observer die neue Größe und der Tooltip sitzt richtig.
  function chHover(svgEl, show, hide, cfg) {
    [].slice.call(svgEl.querySelectorAll('[data-hit]')).forEach(function (h, i) {
      h.addEventListener('pointerenter', function () { show(i); });
    });
    var pin = cfg && cfg.tipPin;
    svgEl.addEventListener('pointerleave', function () {
      if (pin != null) show(pin); else hide();
    });
    if (pin == null) return;
    if (window.ResizeObserver) new ResizeObserver(function () { show(pin); }).observe(svgEl);
    else requestAnimationFrame(function () { show(pin); });
  }

  function chartCartesian(root, cfg) {
    var type = cfg.type;
    var labels = cfg.labels || [];
    var series = cfg.series || [];
    var N = labels.length;
    var grid = cfg.grid !== false;
    var axis = !!cfg.axis;
    var padL = axis ? 42 : 14, padR = 14, padT = 14, padB = 26;
    var x0 = padL, x1 = CH_W - padR, y0 = padT, y1 = CH_H - padB;
    var band = (x1 - x0) / N;
    function xc(i) { return x0 + band * (i + 0.5); }

    var max = type === 'stacked'
      ? (cfg.max || chNiceMax(Math.max.apply(null, labels.map(function (_, i) { return series.reduce(function (a, se) { return a + (se.data[i] || 0); }, 0); })) || 1))
      : chSeriesMax(cfg, series);
    function yv(v) { return y1 - (v / max) * (y1 - y0); }

    var ticks = cfg.ticks || 4, s = '';
    for (var t = 0; t <= ticks; t++) {
      var val = max * t / ticks, gy = yv(val);
      if (grid) s += '<line x1="' + x0 + '" y1="' + gy.toFixed(1) + '" x2="' + x1 + '" y2="' + gy.toFixed(1) + '" stroke="var(--border)" stroke-width="1"/>';
      if (axis) s += chText(padL - 6, gy + 3, chNum(val), 'end', 10);
    }
    if (axis) s += '<line x1="' + x0 + '" y1="' + y0 + '" x2="' + x0 + '" y2="' + y1 + '" stroke="var(--muted-foreground)" stroke-width="1"/>';

    if (type === 'bar' || type === 'bars') {
      var m = type === 'bar' ? 1 : series.length, bw = band * 0.62 / m;
      series.forEach(function (se, si) {
        var g = '<g fill="' + chCol(se.color, si) + '">';
        for (var i = 0; i < N; i++) {
          var v = se.data[i] || 0, by = yv(v), bh = y1 - by;
          var cx = type === 'bar' ? xc(i) : (xc(i) - band * 0.31 + bw * (si + 0.5));
          g += '<rect data-cat="' + i + '" x="' + (cx - bw / 2).toFixed(1) + '" y="' + by.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(0, bh).toFixed(1) + '" rx="3"/>';
        }
        s += g + '</g>';
      });
    } else if (type === 'stacked') {
      var w = band * 0.62;
      for (var i = 0; i < N; i++) {
        var acc = 0;
        for (var si = 0; si < series.length; si++) {
          var v = series[si].data[i] || 0, yTop = yv(acc + v), yBot = yv(acc);
          s += '<rect data-cat="' + i + '" fill="' + chCol(series[si].color, si) + '" x="' + (xc(i) - w / 2).toFixed(1) + '" y="' + yTop.toFixed(1) +
            '" width="' + w.toFixed(1) + '" height="' + Math.max(0, yBot - yTop).toFixed(1) + '" rx="' + (si === series.length - 1 ? '3' : '0') + '"/>';
          acc += v;
        }
      }
    } else { // line | lines | step | smooth
      series.forEach(function (se, si) {
        var col = chCol(se.color, si);
        var pts = se.data.map(function (v, i) { return [xc(i), yv(v)]; });
        var d;
        if (type === 'step') { d = 'M' + pts[0][0].toFixed(1) + ',' + pts[0][1].toFixed(1); for (var k = 1; k < pts.length; k++) d += 'H' + pts[k][0].toFixed(1) + 'V' + pts[k][1].toFixed(1); }
        else if (type === 'smooth') { d = chSmooth(pts); }
        else { d = 'M' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join('L'); }
        if (cfg.area && series.length === 1 && type !== 'step') {
          s += '<path d="' + d + 'L' + pts[pts.length - 1][0].toFixed(1) + ',' + y1 + 'L' + pts[0][0].toFixed(1) + ',' + y1 + 'Z" fill="' + col + '" fill-opacity="0.12"/>';
        }
        s += '<path d="' + d + '" fill="none" stroke="' + col + '" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>';
      });
      s += '<line data-focus-line x1="0" y1="' + y0 + '" x2="0" y2="' + y1 + '" stroke="var(--muted-foreground)" stroke-width="1" stroke-dasharray="4 3" opacity="0"/>';
      series.forEach(function (se, si) { s += '<circle data-focus-dot="' + si + '" r="4.5" fill="var(--background)" stroke="' + chCol(se.color, si) + '" stroke-width="2.5" opacity="0"/>'; });
    }

    if (cfg.xLabels !== false) for (var i = 0; i < N; i++) s += chText(xc(i), y1 + 16, labels[i], 'middle', 10);
    for (var i = 0; i < N; i++) s += '<rect data-hit="' + i + '" x="' + (x0 + band * i).toFixed(1) + '" y="' + y0 + '" width="' + band.toFixed(1) + '" height="' + (y1 - y0) + '" fill="transparent"/>';

    var m = chMount(root, cfg, '<svg viewBox="0 0 ' + CH_W + ' ' + CH_H + '" style="display:block;width:100%" fill="none">' + s + '</svg>');
    var svgEl = m.svgEl, tip = m.tip;
    var catRects = [].slice.call(svgEl.querySelectorAll('rect[data-cat]'));
    var focusLine = svgEl.querySelector('[data-focus-line]');
    var focusDots = [].slice.call(svgEl.querySelectorAll('[data-focus-dot]'));

    function show(i) {
      var rows = chRows(series, i, cfg.unit, cfg);
      if (type === 'stacked') rows.reverse();
      tip.innerHTML = chTipHtml(labels[i], rows, cfg, chTotal(cfg, series, i));
      var topVal = type === 'stacked'
        ? series.reduce(function (a, se) { return a + (se.data[i] || 0); }, 0)
        : Math.max.apply(null, series.map(function (se) { return se.data[i] || 0; }));
      chPlace(tip, svgEl, root, xc(i), yv(topVal), CH_W, CH_H);
      catRects.forEach(function (r) { r.style.opacity = (+r.getAttribute('data-cat') === i) ? '1' : '0.3'; });
      if (focusLine) { focusLine.setAttribute('x1', xc(i)); focusLine.setAttribute('x2', xc(i)); focusLine.setAttribute('opacity', '0.5'); }
      focusDots.forEach(function (d, si) { d.setAttribute('cx', xc(i)); d.setAttribute('cy', yv(series[si].data[i] || 0)); d.setAttribute('opacity', '1'); });
    }
    function hide() {
      tip.style.opacity = '0';
      catRects.forEach(function (r) { r.style.opacity = '1'; });
      if (focusLine) focusLine.setAttribute('opacity', '0');
      focusDots.forEach(function (d) { d.setAttribute('opacity', '0'); });
    }
    chHover(svgEl, show, hide, cfg);
  }

  // Zeichenkasten runder Charts: so groß, wie die Geometrie WIRKLICH reicht. Ein angeschnittener
  // Kreis (sweep < 360) füllt das Quadrat nicht — ohne Beschnitt hängt das Chart in einer halb
  // leeren Fläche. Vorher wurde nur der eine Fall „start genau 180°" behandelt, und zwar nur in
  // der Höhe; ein Halbkreis als start:-90/sweep:180 (rechte Hälfte) blieb im leeren Kasten.
  // Jetzt allgemein: die echte Bounding-Box des Winkelbereichs. Extrema eines Bogens liegen an
  // den Rändern und an jedem Vielfachen von 90° dazwischen; der Mittelpunkt gehört immer dazu
  // (Treffer-Keile laufen dorthin, die Mittelschrift sitzt dort).
  // Rückgabe: viewBox-Zeichenkette + Faktor f = Kastenbreite/VBW. Die CSS-Breite wird mit f
  // multipliziert, damit der Beschnitt nur Leerraum wegnimmt und den MASSSTAB nicht ändert —
  // sonst würde ein Halbkreis größer gezeichnet als der ganze Kreis daneben.
  // `vorlaufDeg`: Grad VOR dem Startwinkel, die zum Inhalt gehören. Nötig, weil die
  // Radial-Beschriftung vor dem Balkenanfang sitzt — ohne diesen Zuschlag schnitt der Kasten bei
  // sweep < 360 genau die Namen ab (gemessen: bei start:-90/sweep:180 lagen alle Label-Kästen
  // links außerhalb der viewBox). Ein Kasten, der den Inhalt beschneidet, ist schlimmer als ein
  // etwas zu großer.
  function chRundBox(cx, cy, rMax, startDeg, sweepDeg, VBW, VBH, rand, vorlaufDeg) {
    rand = rand == null ? 14 : rand;
    if (!(sweepDeg < 360)) return { vb: '0 0 ' + VBW + ' ' + VBH, f: 1, x: 0, y: 0, w: VBW, h: VBH };
    var a0 = startDeg - (vorlaufDeg || 0), a1 = startDeg + sweepDeg, xs = [0], ys = [0];
    function nimm(deg) {
      var a = deg * Math.PI / 180;
      xs.push(rMax * Math.cos(a)); ys.push(rMax * Math.sin(a));
    }
    nimm(a0); nimm(a1);
    for (var k = Math.ceil(a0 / 90) * 90; k <= a1; k += 90) nimm(k);
    var x0 = Math.max(0, Math.floor(cx + Math.min.apply(null, xs) - rand));
    var x1 = Math.min(VBW, Math.ceil(cx + Math.max.apply(null, xs) + rand));
    var y0 = Math.max(0, Math.floor(cy + Math.min.apply(null, ys) - rand));
    var y1 = Math.min(VBH, Math.ceil(cy + Math.max.apply(null, ys) + rand));
    return { vb: x0 + ' ' + y0 + ' ' + (x1 - x0) + ' ' + (y1 - y0), f: (x1 - x0) / VBW, x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  // Bogenpfad für <textPath>: von Winkel a nach b (Radiant) auf Radius R. Die LAUFRICHTUNG
  // entscheidet, wie der Text steht — deshalb ist sie ein Parameter und keine Konstante.
  function chArcPath(cx, cy, R, a, b) {
    var large = Math.abs(b - a) > Math.PI ? 1 : 0;
    return 'M' + (cx + R * Math.cos(a)).toFixed(2) + ',' + (cy + R * Math.sin(a)).toFixed(2) +
      'A' + R.toFixed(2) + ' ' + R.toFixed(2) + ' 0 ' + large + ' ' + (b > a ? 1 : 0) + ' ' +
      (cx + R * Math.cos(b)).toFixed(2) + ',' + (cy + R * Math.sin(b)).toFixed(2);
  }
  var chUid = 0;   // eindeutige IDs für <textPath href> — mehrere Charts pro Seite sind der Normalfall

  // Mittelschrift runder Charts (Donut-Loch, Radial-Mitte) — eine Quelle für beide Renderer.
  function chCenterText(cx, cy, center) {
    if (!center) return '';
    var dy = center.dy || 0, s = '';
    if (center.value != null) s += '<text x="' + cx + '" y="' + (cy - 2 + dy) + '" text-anchor="middle" fill="var(--foreground)" style="font-size:17px;font-weight:600">' + calEsc(center.value) + '</text>';
    if (center.label != null) s += '<text x="' + cx + '" y="' + (cy + 13 + dy) + '" text-anchor="middle" fill="var(--muted-foreground)" style="font-size:9px">' + calEsc(center.label) + '</text>';
    return s;
  }

  // ---- Kreis: Torte UND Donut aus EINER Geometrie ---------------------------
  // Ein Band wird als gestrichelte Kreislinie gezeichnet: Radius = Bandmitte, Strichbreite =
  // Banddicke. Damit deckt derselbe Code beide Formen ab — "inner" ist das Loch als Anteil des
  // Außenradius: 0 lässt die Strichbreite bis zum Mittelpunkt reichen (volle Torte), >0 lässt ein
  // Loch (Donut). Kein zweiter Renderer für Torten, kein Ringsektor-Pfad je Segment.
  // Optionen: inner · gap (Lücke zwischen Segmenten, 0 = ohne Trenner) · start/sweep (Grad,
  // sweep 180 = Halbkreis) · values:true (absolute Werte statt Anteil im Tooltip) ·
  // sliceLabels "percent"|"value"|"name" (IM Segment) · nameLabels:true (Namen AUSSEN) ·
  // center {value,label,dy}. MEHRERE Serien = konzentrische Ringe (gestapelte Torte).
  function chartPie(root, cfg) {
    var labels = cfg.labels || [];
    var reihen = (cfg.series && cfg.series.length ? cfg.series : [{ data: [] }]);
    var nameLab = !!cfg.nameLabels;
    // Namen AUSSEN brauchen Rand: dann dieselbe weite viewBox wie das Radar (240x188), sonst der
    // knappe Kreiskasten. Der Kreis bleibt in beiden Fällen gleich groß (rOut), nur der Rahmen
    // wächst — das svg skaliert über die Breite mit.
    var VBW = nameLab ? 240 : 140, VBH = nameLab ? 188 : 140;
    var cx = VBW / 2, cy = VBH / 2, rOut = 62;
    // Standard-Loch: Donut wie bisher (42/62 -> R 52, Strichbreite 20), Torte ohne Loch.
    var inner = cfg.inner != null ? cfg.inner : (cfg.type === 'donut' ? 42 / 62 : 0);
    var rIn = rOut * inner;
    var startDeg = cfg.start != null ? cfg.start : -90;
    var sweepDeg = Math.min(360, cfg.sweep != null ? cfg.sweep : 360);
    var gap = cfg.gap != null ? cfg.gap : 1.5;
    var ringGap = 3;
    var pitch = (rOut - rIn) / reihen.length;
    var bh = Math.max(3, pitch - (reihen.length > 1 ? ringGap : 0));

    var segs = '', hits = '', labs = '', hitMap = [], geo = [];
    reihen.forEach(function (se, si) {
      var data = se.data || [], colors = se.colors || [];
      var bandOut = rOut - si * pitch, R = bandOut - bh / 2, C = 2 * Math.PI * R;
      // "summe" ist der TEILER für den Anteil (darf nie 0 werden), "roh" die echte Summe für die
      // Summenzeile — sonst behauptete ein leerer Ring im Tooltip eine Gesamtmenge von 1.
      var roh = data.reduce(function (a, b) { return a + b; }, 0);
      var summe = roh || 1;
      var voll = C * sweepDeg / 360;
      var off = 0;
      geo.push({ R: R, bh: bh, summe: summe, roh: roh, data: data, colors: colors, mid: [] });
      data.forEach(function (v, i) {
        var len = v / summe * voll, sicht = Math.max(0, len - gap);
        segs += '<circle data-seg="' + hitMap.length + '" cx="' + cx + '" cy="' + cy + '" r="' + R.toFixed(2) +
          '" fill="none" stroke="' + chCol(colors[i] || se.color, i) + '" stroke-width="' + bh.toFixed(2) +
          '" stroke-dasharray="' + sicht.toFixed(2) + ' ' + Math.max(0.01, C - sicht).toFixed(2) +
          '" stroke-dashoffset="' + (-off).toFixed(2) + '" transform="rotate(' + startDeg + ' ' + cx + ' ' + cy + ')"/>';
        var a0 = startDeg * Math.PI / 180 + off / C * 2 * Math.PI;
        var a1 = startDeg * Math.PI / 180 + (off + len) / C * 2 * Math.PI;
        var mid = (a0 + a1) / 2;
        geo[si].mid.push(mid);
        // Treffer: Ringsektor über GENAU diesem Band (Keil außen minus Keil innen als zweiter
        // Pfad wäre teuer — ein Keil bis Bandaußenrand genügt, weil die Bänder disjunkt sind
        // und der innere Keil vom nächsten Ring überdeckt wird; Reihenfolge außen -> innen).
        hits += '<path data-hit="' + hitMap.length + '" d="' + chWedge(cx, cy, bandOut + 2, a0, a1) + '" fill="transparent"/>';
        hitMap.push({ si: si, i: i });
        // Beschriftung IM Segment nur, wenn das Segment sie trägt: unter ~8 % des Kreises läuft
        // der Text über die Nachbarn und macht die Stelle unlesbar — dann lieber keine Zahl
        // (der Tooltip nennt sie ohnehin).
        if (cfg.sliceLabels && v > 0 && len / voll >= 0.08) {
          var txt = cfg.sliceLabels === 'value' ? chNum(v)
            : cfg.sliceLabels === 'name' ? (labels[i] || '')
              : Math.round(v / summe * 100) + ' %';
          // Text AUF einer Datenfarbe: eine feste Füllfarbe kann hier nicht funktionieren —
          // --chart-1…5 laufen über die halbe Helligkeitsskala, gemessen 1.80:1 (hell auf
          // chart-1) bzw. 2.27:1 (dunkel auf chart-5), also unter jeder Schwelle. Statt zu
          // raten, welche Farbe „meistens" trägt: der Text nimmt die normale Textfarbe und
          // bekommt eine Kontur in der Grundfläche (paint-order legt sie HINTER die Füllung).
          // Damit liest er auf jedem Segment jeder Palette, in hell wie dunkel — dieselbe
          // Technik, die Kartenbeschriftungen seit je benutzen.
          labs += '<text x="' + (cx + R * Math.cos(mid)).toFixed(1) + '" y="' + (cy + R * Math.sin(mid) + 3).toFixed(1) +
            '" text-anchor="middle" fill="var(--foreground)" stroke="var(--background)"' +
            ' stroke-width="2.5" stroke-linejoin="round" style="font-size:9px;font-weight:600;' +
            'paint-order:stroke fill">' + calEsc(txt) + '</text>';
        }
        off += len;
      });
      if (nameLab && si === 0) data.forEach(function (v, i) {
        var mid = geo[si].mid[i], dx = Math.cos(mid);
        var anchor = Math.abs(dx) < 0.3 ? 'middle' : (dx > 0 ? 'start' : 'end');
        labs += chText((cx + rOut * 1.14 * dx).toFixed(1), (cy + rOut * 1.14 * Math.sin(mid) + 3).toFixed(1), labels[i] || '', anchor, 9);
      });
    });

    // Treffer außen -> innen ins Markup, damit der äußere Keil den inneren nicht verdeckt:
    // sie liegen in Serien-Reihenfolge, der spätere (innere) gewinnt beim Zeiger.
    // Namen AUSSEN ragen über den Kreis hinaus — dann muss der Kasten bis dorthin reichen.
    var box = chRundBox(cx, cy, nameLab ? rOut * 1.14 : rOut, startDeg, sweepDeg, VBW, VBH, nameLab ? 30 : 14);
    var svg = '<svg viewBox="' + box.vb +
      '" style="display:block;margin:0 auto;width:' + Math.round((nameLab ? 240 : 160) * box.f) + 'px" fill="none">' + segs + labs +
      chCenterText(cx, cy, cfg.center) + hits + '</svg>';
    var m = chMount(root, cfg, svg);
    var svgEl = m.svgEl, tip = m.tip;
    var segEls = [].slice.call(svgEl.querySelectorAll('[data-seg]'));
    function show(k) {
      var z = hitMap[k], g = geo[z.si], v = g.data[z.i] || 0;
      var farbe = chCol(g.colors[z.i] || reihen[z.si].color, z.i);
      var wert = cfg.values ? chNum(v) + (cfg.unit || '') : Math.round(v / g.summe * 100) + ' %';
      var name = reihen.length > 1 ? (reihen[z.si].name || '') : (cfg.values ? (reihen[0].name || '') : (cfg.unit || 'Anteil'));
      // Summenzeile: das Ganze, auf das sich der Anteil bezieht — die Summe DIESES Rings.
      tip.innerHTML = chTipHtml(labels[z.i] || '', [{ color: farbe, label: name, value: wert, suffix: cfg.tipUnit }],
        cfg, chTotalVon(cfg, g.roh));
      chPlaceRadial(tip, svgEl, root, cx - box.x, cy - box.y, g.mid[z.i], box.w, g.R + g.bh / 2);   // Kreis-Referenz: Bandaußenrand
      segEls.forEach(function (e, j) { e.style.opacity = j === k ? '1' : '0.3'; });
    }
    function hide() { tip.style.opacity = '0'; segEls.forEach(function (e) { e.style.opacity = '1'; }); }
    chHover(svgEl, show, hide, cfg);
  }

  // ---- Radial: Balken auf Kreisbögen --------------------------------------
  // Je Kategorie EIN konzentrischer Bogen (außen = erste Kategorie) auf einer vollen Spur; die
  // Bogenlänge ist der Wert am Maßstab (max). Technik wie beim Kreis: gestrichelte Kreislinie,
  // Strichbreite = Bandhöhe — deshalb kein eigener Pfad-Generator.
  // Optionen: max · inner (Lochanteil) · start/sweep (Grad; sweep 180 = Halbkreis) ·
  // track:false (ohne Spur) · grid:true (Polargitter) · round:false (eckige Enden; ein Stapel
  // rechnet immer mit eckigen) · barLabels:true (Name dem Bogen folgend vor dem Balkenanfang;
  // im STAPEL ohne Wirkung — dort liegen alle Werte auf EINEM Band, ein Name hätte keinen
  // eigenen Bogen davor. Das ist eine Grenze, keine Panne: der Tooltip nennt die Namen) ·
  // center {value,label,dy} · stack:true (EIN Band, Werte hintereinander gestapelt statt je
  // Kategorie ein Ring) · tipTotal (Summenzeile: Stapel = das Band, sonst alle Ringe).
  function chartRadial(root, cfg) {
    var labels = cfg.labels || [];
    var se0 = (cfg.series && cfg.series[0]) || { data: [] };
    var data = se0.data || [], colors = se0.colors || [];
    var VB = 150, cx = VB / 2, cy = VB / 2, rOut = 66;
    var inner = cfg.inner != null ? cfg.inner : 0.3;
    var rIn = rOut * inner;
    var startDeg = cfg.start != null ? cfg.start : -90;
    var sweepDeg = Math.min(360, cfg.sweep != null ? cfg.sweep : 360);
    var stack = !!cfg.stack;
    // Runde Kappen ragen eine HALBE Bandbreite über jedes Segmentende hinaus. Bei einem einzelnen
    // Balken ist das der gewollte Abschluss; bei gestapelten Segmenten auf EINEM Band überlappen
    // sich dadurch die Nachbarn (bei dickem Band um bh) und die Grenzen wandern sichtbar. Ein
    // Stapel bekommt deshalb immer butt-Kappen — nicht als Voreinstellung, sondern als Geometrie:
    // "round" wäre dort schlicht falsch gerechnet.
    var kappe = (cfg.round === false || stack) ? 'butt' : 'round';
    var max = cfg.max || (stack
      ? chNiceMax(data.reduce(function (a, b) { return a + b; }, 0) || 1)
      : chNiceMax(Math.max.apply(null, data) || 1));

    var n = stack ? 1 : Math.max(1, data.length);
    var pitch = (rOut - rIn) / n;
    var bh = Math.max(3, pitch - (n > 1 ? 3 : 0));
    // Ein Band je Kategorie (bzw. EIN Band beim Stapel): Radius der Bandmitte + Kreisumfang.
    function band(k) {
      var bandOut = rOut - k * pitch, R = bandOut - bh / 2;
      return { bandOut: bandOut, R: R, C: 2 * Math.PI * R, voll: 2 * Math.PI * R * sweepDeg / 360 };
    }
    function bogen(b, laenge, off, farbe, breite, index) {
      var sicht = Math.max(0, laenge);
      return '<circle' + (index != null ? ' data-seg="' + index + '"' : '') + ' cx="' + cx + '" cy="' + cy +
        '" r="' + b.R.toFixed(2) + '" fill="none" stroke="' + farbe + '" stroke-width="' + breite.toFixed(2) +
        '" stroke-linecap="' + kappe + '" stroke-dasharray="' + sicht.toFixed(2) + ' ' +
        Math.max(0.01, b.C - sicht).toFixed(2) + '" stroke-dashoffset="' + (-off).toFixed(2) +
        '" transform="rotate(' + startDeg + ' ' + cx + ' ' + cy + ')"/>';
    }

    // Beschriftung eines Radialbalkens. Sie FOLGT dem Bogen (<textPath> auf einem <path> mit ID) —
    // gerader Text auf einem gekrümmten Band hängt sonst halb daneben, und weil alle Bänder am
    // GLEICHEN Winkel beginnen, stapelten sich die Namen früher zu einer senkrechten Säule.
    // Entlang des Bogens laufen sie stattdessen jeder auf seinem eigenen Ring und stoßen nie
    // zusammen. Sie sitzen VOR dem Balkenanfang, also auf der Spur (--muted) bzw. außerhalb eines
    // angeschnittenen Kreises auf der Fläche — beides Untergründe, auf denen das ROLLEN-PAAR
    // muted/muted-foreground in hell UND dunkel liest. Auf dem Balken selbst ginge das nicht: die
    // Serienfarben --chart-1…5 laufen über die halbe Helligkeitsskala, dort ist keine feste
    // Textfarbe in beiden Erscheinungsbildern lesbar (var(--background) war im Dunkelmodus
    // fast schwarz auf dunklem Band).
    var labelVorlaufDeg = 0;   // wird von radialLabel gefüllt, vom Kasten gelesen

    function radialLabel(b, len, txt) {
      if (!txt) return '';
      var fs = Math.min(9, bh * 0.8);                       // an die BANDHÖHE gebunden, nicht fest
      var a0 = startDeg * Math.PI / 180;
      // Abstand zum Balkenanfang: eine runde Kappe ragt bh/2 zurück, sonst nur Luft.
      var luft = (kappe === 'round' ? bh / 2 : 0) + 3;
      var frei = b.C - len - luft;                          // Bogenlänge ohne Balken (Spur + Freiraum)
      var brauch = txt.length * fs * 0.58;                  // Schätzung der Textbreite
      if (frei < brauch) return '';                         // kein Platz -> lieber nichts (der Tooltip nennt den Namen)
      var aEnd = a0 - luft / b.R, dA = brauch / b.R;
      // Grösster Vorlauf über alle Balken — der Kasten rechnet damit (s. chRundBox-Aufruf).
      labelVorlaufDeg = Math.max(labelVorlaufDeg, ((luft + brauch) / b.R) * 180 / Math.PI);
      // Laufrichtung entscheidet, wie der Text STEHT: auf der unteren Hälfte stünde er im
      // Uhrzeigersinn auf dem Kopf, dort muss der Pfad gegen den Uhrzeigersinn laufen.
      var unten = Math.sin(aEnd - dA / 2) > 0;
      var id = 'c22-bl-' + (++chUid);
      var d = unten ? chArcPath(cx, cy, b.R, aEnd, aEnd - dA) : chArcPath(cx, cy, b.R, aEnd - dA, aEnd);
      return '<path id="' + id + '" d="' + d + '" fill="none" stroke="none"/>' +
        '<text fill="' + chCol('muted-foreground', 0) + '" dominant-baseline="central" text-anchor="' +
        (unten ? 'start' : 'end') + '" style="font-size:' + fs.toFixed(1) + 'px;font-weight:600">' +
        '<textPath href="#' + id + '" startOffset="' + (unten ? '0%' : '100%') + '">' + calEsc(txt) + '</textPath></text>';
    }

    var gitter = '', spuren = '', segs = '', hits = '', labs = '', ziele = [];
    if (cfg.grid) {
      for (var g = 0; g <= n; g++) {
        var rg = rIn + (rOut - rIn) * g / n;
        gitter += '<circle cx="' + cx + '" cy="' + cy + '" r="' + rg.toFixed(2) + '" fill="none" stroke="var(--border)" stroke-width="1"/>';
      }
      var speichen = Math.max(4, labels.length || 6);
      for (var s2 = 0; s2 < speichen; s2++) {
        var a = startDeg * Math.PI / 180 + s2 * sweepDeg / speichen * Math.PI / 180;
        gitter += '<line x1="' + (cx + rIn * Math.cos(a)).toFixed(1) + '" y1="' + (cy + rIn * Math.sin(a)).toFixed(1) +
          '" x2="' + (cx + rOut * Math.cos(a)).toFixed(1) + '" y2="' + (cy + rOut * Math.sin(a)).toFixed(1) +
          '" stroke="var(--border)" stroke-width="1"/>';
      }
    }

    if (stack) {
      var b0 = band(0), offS = 0;
      if (cfg.track !== false) spuren += bogen(b0, b0.voll, 0, 'var(--muted)', bh);
      data.forEach(function (v, i) {
        var len = Math.max(0, v) / max * b0.voll;
        segs += bogen(b0, len, offS, chCol(colors[i] || se0.color, i), bh, i);
        var aMitte = startDeg * Math.PI / 180 + (offS + len / 2) / b0.C * 2 * Math.PI;
        hits += '<path data-hit="' + i + '" d="' + chWedge(cx, cy, b0.bandOut + 2,
          startDeg * Math.PI / 180 + offS / b0.C * 2 * Math.PI,
          startDeg * Math.PI / 180 + (offS + len) / b0.C * 2 * Math.PI) + '" fill="transparent"/>';
        ziele.push({ R: b0.R, a: aMitte, v: v, farbe: chCol(colors[i] || se0.color, i) });
        offS += len;
      });
    } else {
      data.forEach(function (v, i) {
        var b = band(i), len = Math.max(0, v) / max * b.voll;
        if (cfg.track !== false) spuren += bogen(b, b.voll, 0, 'var(--muted)', bh);
        segs += bogen(b, len, 0, chCol(colors[i] || se0.color, i), bh, i);
        var aEnd = startDeg * Math.PI / 180 + len / b.C * 2 * Math.PI;
        // Trefferfläche: das ganze Band über die volle Umdrehung — der Zeiger zählt je RING,
        // nicht je Winkel (ein Radialbalken ist ein Balken, kein Segment).
        hits += '<circle data-hit="' + i + '" cx="' + cx + '" cy="' + cy + '" r="' + b.R.toFixed(2) +
          '" fill="none" stroke="transparent" stroke-width="' + bh.toFixed(2) + '" stroke-dasharray="' +
          b.voll.toFixed(2) + ' ' + Math.max(0.01, b.C - b.voll).toFixed(2) +
          '" transform="rotate(' + startDeg + ' ' + cx + ' ' + cy + ')"/>';
        ziele.push({ R: b.R, a: aEnd, v: v, farbe: chCol(colors[i] || se0.color, i) });
        if (cfg.barLabels) labs += radialLabel(b, len, labels[i] || '');
      });
    }

    // Der Kasten muss den Label-VORLAUF kennen: die Namen sitzen vor dem Balkenanfang, also
    // ausserhalb von [start, start+sweep]. radialLabel merkt sich den grössten benötigten
    // Winkel; ohne diesen Zuschlag schnitt der Kasten bei sweep < 360 genau die Namen ab.
    var box = chRundBox(cx, cy, rOut, startDeg, sweepDeg, VB, VB, null, labelVorlaufDeg);
    var svg = '<svg viewBox="' + box.vb +
      '" style="display:block;margin:0 auto;width:' + Math.round(200 * box.f) + 'px" fill="none">' +
      gitter + spuren + segs + labs + chCenterText(cx, cy, cfg.center) + hits + '</svg>';
    var m = chMount(root, cfg, svg);
    var svgEl = m.svgEl, tip = m.tip;
    var segEls = [].slice.call(svgEl.querySelectorAll('[data-seg]'));
    function show(i) {
      var z = ziele[i];
      // Summenzeile: beim Stapel die Summe des Bandes, sonst die aller Ringe — in beiden Fällen
      // das Ganze, in dem dieser Balken steht.
      tip.innerHTML = chTipHtml(labels[i] || '', [{
        color: z.farbe, label: se0.name || labels[i] || '',
        value: chNum(z.v) + (cfg.unit || ''), suffix: cfg.tipUnit, icon: se0.icon,
      }], cfg, chTotalVon(cfg, data.reduce(function (a, v) { return a + v; }, 0)));
      // Punkt-Referenz: Bogenende auf der Bandmitte (extraR = halbe Bandhöhe, damit der
      // Tooltip nicht auf dem Band klebt).
      chPlaceRadial(tip, svgEl, root, cx + z.R * Math.cos(z.a) - box.x, cy + z.R * Math.sin(z.a) - box.y, z.a, box.w, bh / 2);
      segEls.forEach(function (e, j) { e.style.opacity = j === i ? '1' : '0.3'; });
    }
    function hide() { tip.style.opacity = '0'; segEls.forEach(function (e) { e.style.opacity = '1'; }); }
    chHover(svgEl, show, hide, cfg);
  }

  // Netzdiagramm. Ausführungen: grid:false (ohne Netz) · gridShape:"circle" (Kreisringe statt
  // Vielecke) · spokes:false (Ringe ohne Speichen) · fill:false (nur Linien) · dots:false (ohne
  // Punkte) · rings:<anzahl> (Ringe des Netzes, Standard 3).
  function chartRadar(root, cfg) {
    var labels = cfg.labels || [], series = cfg.series || [], n = labels.length;
    var VBW = 240, VBH = 188, cx = VBW / 2, cy = 94, R = 62;   // breite viewBox -> Achsenlabels ragen nicht raus
    var max = chSeriesMax(cfg, series);
    var mitPunkten = cfg.dots !== false;
    function ang(i) { return -Math.PI / 2 + i * 2 * Math.PI / n; }
    function pt(i, frac) { var a = ang(i); return [cx + R * frac * Math.cos(a), cy + R * frac * Math.sin(a)]; }
    function ring(k) { var p = []; for (var i = 0; i < n; i++) { var q = pt(i, k); p.push(q[0].toFixed(1) + ',' + q[1].toFixed(1)); } return p.join(' '); }
    var s = '';
    if (cfg.grid !== false) {
      var anzahl = cfg.rings || 3, stufen = [];
      for (var k = 1; k <= anzahl; k++) stufen.push(k / anzahl);
      stufen.forEach(function (k) {
        s += cfg.gridShape === 'circle'
          ? '<circle cx="' + cx + '" cy="' + cy + '" r="' + (R * k).toFixed(1) + '" stroke="var(--border)" stroke-width="1" fill="none"/>'
          : '<polygon points="' + ring(k) + '" stroke="var(--border)" stroke-width="1" fill="none"/>';
      });
      if (cfg.spokes !== false) for (var i = 0; i < n; i++) { var p = pt(i, 1); s += '<line x1="' + cx + '" y1="' + cy + '" x2="' + p[0].toFixed(1) + '" y2="' + p[1].toFixed(1) + '" stroke="var(--border)" stroke-width="1"/>'; }
    }
    series.forEach(function (se, si) {
      var col = chCol(se.color, si);
      var pts = se.data.map(function (v, i) { return pt(i, v / max); });
      s += '<polygon points="' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') +
        '" fill="' + col + '" fill-opacity="' + (cfg.fill === false ? '0' : '0.2') + '" stroke="' + col +
        '" stroke-width="2.5" stroke-linejoin="round"/>';
      if (mitPunkten) pts.forEach(function (p, i) { s += '<circle data-dot="' + si + '-' + i + '" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3" fill="' + col + '"/>'; });
    });
    for (var i = 0; i < n; i++) {
      var p = pt(i, 1.16), dx = Math.cos(ang(i));
      var anchor = Math.abs(dx) < 0.3 ? 'middle' : (dx > 0 ? 'start' : 'end');
      s += chText(p[0].toFixed(1), (p[1] + 3).toFixed(1), labels[i], anchor, 9);
    }
    for (var i = 0; i < n; i++) { s += '<path data-hit="' + i + '" d="' + chWedge(cx, cy, R * 1.12, ang(i) - Math.PI / n, ang(i) + Math.PI / n) + '" fill="transparent"/>'; }
    var m = chMount(root, cfg, '<svg viewBox="0 0 ' + VBW + ' ' + VBH + '" style="display:block;margin:0 auto;width:230px" fill="none">' + s + '</svg>');
    var svgEl = m.svgEl, tip = m.tip;
    function show(i) {
      tip.innerHTML = chTipHtml(labels[i], chRows(series, i, cfg.unit, cfg), cfg, chTotal(cfg, series, i));
      var vtx = pt(i, 1);                              // Punkt-Referenz: Polygon-Vertex auf der Achse (extraR=0)
      chPlaceRadial(tip, svgEl, root, vtx[0], vtx[1], ang(i), VBW);
      series.forEach(function (se, si) { var d = svgEl.querySelector('[data-dot="' + si + '-' + i + '"]'); if (d) d.setAttribute('r', '5'); });
    }
    function hide() { tip.style.opacity = '0'; [].slice.call(svgEl.querySelectorAll('[data-dot]')).forEach(function (d) { d.setAttribute('r', '3'); }); }
    chHover(svgEl, show, hide, cfg);
  }

  function wireChart(root) {
    if (root.dataset.c22ChartWired) return;
    root.dataset.c22ChartWired = '1';
    var cfg;
    try { cfg = JSON.parse(root.dataset.chart || '{}'); } catch (e) { return; }
    if (cfg.type === 'pie' || cfg.type === 'donut') return chartPie(root, cfg);
    if (cfg.type === 'radial') return chartRadial(root, cfg);
    if (cfg.type === 'radar') return chartRadar(root, cfg);
    chartCartesian(root, cfg);
  }

  // ---- Reiter per Adresse (Deep-Link) ---------------------------------------
  // [data-tab-hash] auf einem .tabs: zeigt der Anker der Adresse auf einen Reiter-Knopf ODER auf
  // ein Element IN einem Panel, wird dieser Reiter geöffnet und das Ziel angesprungen. Ohne das
  // ist ein Link in ein verborgenes Panel wirkungslos (das Panel trägt `hidden`, der Browser kann
  // nicht dorthin springen) — Galerie-Screenshots und teilbare Adressen brauchen genau das.
  // BEWUSST NUR LESEND: ein Klick auf einen Reiter ändert die Adresse nicht, damit die
  // Zurück-Taste nicht zur Reiter-Historie verkommt.
  function wireTabHash(tabs) {
    if (tabs.dataset.c22TabHashWired) return;
    tabs.dataset.c22TabHashWired = '1';
    function anwenden() {
      var id = (location.hash || '').slice(1);
      if (!id) return;
      var ziel = document.getElementById(id);
      if (!ziel || !tabs.contains(ziel)) return;
      var knopf = ziel.getAttribute('role') === 'tab' ? ziel : null;
      if (!knopf) {
        var panel = ziel.closest('[role="tabpanel"]');
        if (!panel || !panel.id) return;
        knopf = tabs.querySelector('[role="tab"][aria-controls="' + panel.id + '"]');
      }
      if (!knopf) return;
      if (knopf.getAttribute('aria-selected') !== 'true') {
        // Basecoats eigene API, wenn sie schon da ist (beide Skripte laufen mit defer, Basecoat
        // verdrahtet zuerst); sonst der Klick, an dem dasselbe JS hängt.
        if (typeof tabs.select === 'function') tabs.select(knopf);
        else knopf.click();
      }
      if (ziel !== knopf) ziel.scrollIntoView();
    }
    // ZWEIMAL, und das ist Absicht: welches Skript zuerst initialisiert, ist nicht garantiert.
    // Läuft Basecoats Reiter-JS noch nicht, gibt es weder `select` noch einen Klick-Handler — der
    // erste Versuch verpufft dann still. Der zweite im nächsten Frame trifft es sicher; ist der
    // Reiter schon offen, tut er nichts (idempotent).
    anwenden();
    requestAnimationFrame(anwenden);
    window.addEventListener('hashchange', anwenden);
  }

  // Scroll-Kanten-Fade: pflegt data-at-start/-end auf [data-scroll-fade]-Containern
  // (horizontal), die Maske dazu liegt in components.css. 1px-Toleranz gegen Subpixel-Rundung.
  function wireScrollFade(el) {
    if (el.dataset.c22FadeWired) return;
    el.dataset.c22FadeWired = '1';
    function update() {
      var max = el.scrollWidth - el.clientWidth;
      var x = Math.abs(el.scrollLeft);
      if (x <= 1) el.setAttribute('data-at-start', ''); else el.removeAttribute('data-at-start');
      if (x >= max - 1) el.setAttribute('data-at-end', ''); else el.removeAttribute('data-at-end');
    }
    el.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    update();
  }

  // ---- Nav-Auswahl (Sidebar, PO 51) -----------------------------------------
  // [data-nav-select] auf einem nav: Klick auf einen Menüpunkt-Link setzt
  // aria-current="page" um (ein aktiver Punkt pro nav) — macht Demo-Sidebars
  // funktional, ohne je Link einen Inline-Handler zu wiederholen.
  function wireNavSelect(nav) {
    if (nav.dataset.c22NavWired) return;
    nav.dataset.c22NavWired = '1';
    nav.addEventListener('click', function (e) {
      var a = e.target.closest('a[role="menuitem"]');
      if (!a || !nav.contains(a)) return;
      e.preventDefault();
      nav.querySelectorAll('[aria-current="page"]').forEach(function (x) { x.removeAttribute('aria-current'); });
      a.setAttribute('aria-current', 'page');
    });
  }

  // ---- Inline-editierbare Tabelle (PO) --------------------------------------
  // Markup: [data-edit-table] auf dem .table-container. Alle tbody-Zellen ohne
  // [data-noedit] werden contenteditable (plaintext-only — kein eingeschlepptes
  // Markup beim Einfügen). data-editing="false" schaltet den Modus ab; ein
  // Umschalter im Beispiel setzt nur dieses Attribut, ein MutationObserver zieht
  // die Zellen nach.
  function wireEditTable(root) {
    if (root.dataset.c22EditWired) return;
    root.dataset.c22EditWired = '1';
    function anwenden() {
      var an = root.dataset.editing !== 'false';
      root.querySelectorAll('tbody td:not([data-noedit])').forEach(function (td) {
        if (an) td.setAttribute('contenteditable', 'plaintext-only');
        else td.removeAttribute('contenteditable');
      });
    }
    anwenden();
    new MutationObserver(anwenden).observe(root, { attributes: true, attributeFilter: ['data-editing'] });
  }

  // ---- Zeichen-Zähler (Textarea, PO 58) -------------------------------------
  // Markup: <p data-char-count> im selben .field wie ein Feld mit maxlength —
  // zählt live beim Tippen („n/max"; ohne maxlength nur „n"). Optional
  // data-char-count="<id>" für ein Ziel außerhalb des eigenen field.
  function wireCharCount(p) {
    if (p.dataset.c22CountWired) return;
    p.dataset.c22CountWired = '1';
    var ziel = p.dataset.charCount
      ? document.getElementById(p.dataset.charCount)
      : (p.closest('.field') || p.parentElement).querySelector('textarea, input');
    if (!ziel) return;
    var max = ziel.getAttribute('maxlength');
    function malen() {
      p.textContent = ziel.value.length + (max ? '/' + max : '');
    }
    ziel.addEventListener('input', malen);
    malen();
  }

  // ---- Copy-Button (Codeblock & Co.) ----------------------------------------
  // Markup: ein Button [data-copy] als Geschwister eines <pre><code> in einem relativen
  // Wrapper. Klick kopiert den Textinhalt des zugehörigen <code> in die Zwischenablage
  // (navigator.clipboard). Feedback: das Icon wechselt ~2s auf ein Häkchen, das aria-label
  // zieht mit (data-copy-done, Default "Kopiert"). Ohne JS / ohne Clipboard-API ist der
  // Button einfach wirkungslos — das Markup bleibt gültig. data-icon-lu hier von Hand
  // benannt (annotate-icons.py fasst nur statisches component-Markup an).
  var COPY_ICO = 'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  var COPY_ICON = '<svg data-icon-lu="copy" ' + COPY_ICO + '><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
  var CHECK_ICON = '<svg data-icon-lu="check" ' + COPY_ICO + '><path d="M20 6 9 17l-5-5"/></svg>';
  function wireCopy(btn) {
    if (btn.dataset.c22CopyWired) return;
    btn.dataset.c22CopyWired = '1';
    var idleHtml = btn.innerHTML || COPY_ICON;
    var idleLabel = btn.getAttribute('aria-label') || 'Code kopieren';
    var doneLabel = btn.dataset.copyDone || 'Kopiert';
    var timer = null;
    btn.addEventListener('click', function () {
      // Zugehöriges <code> im gemeinsamen Wrapper (Button und <pre> sind Geschwister) —
      // oder, im input-group (PO 32g), der Wert des Feldes.
      var scope = btn.closest('[data-copy-scope]') || btn.closest('.input-group') || btn.parentElement;
      var code = scope && scope.querySelector('code');
      var text = code ? code.textContent : '';
      if (!text && scope) {
        var feld = scope.querySelector('input, textarea');
        if (feld) text = feld.value;
      }
      if (!text && scope) {
        var blase = scope.querySelector('.bubble');   // Message 39c: Blasentext kopieren
        if (blase) text = blase.textContent.trim();
      }
      if (!(navigator.clipboard && navigator.clipboard.writeText)) return;
      navigator.clipboard.writeText(text).then(function () {
        btn.innerHTML = CHECK_ICON;
        btn.setAttribute('aria-label', doneLabel);
        clearTimeout(timer);
        timer = setTimeout(function () {
          btn.innerHTML = idleHtml;
          btn.setAttribute('aria-label', idleLabel);
        }, 2000);
      }, function () { /* Zwischenablage verweigert -> stumm, Markup bleibt gültig */ });
    });
  }

  // ---- Reaktions-Leiste (Chat-Reaktionen) -----------------------------------
  // REINE DEMO-/UI-LOGIK — KEINE Persistenz: welche Reaktionen es gibt und wer reagiert
  // hat, weiß nur die App; die bindet das an ihr Backend (Klick abfangen / State setzen).
  // Markup: ein Container [data-reactions] mit Reaktions-Chips (.btn[data-reaction="<emoji>"],
  // Zähler in [data-reaction-count], die EIGENE Reaktion über aria-pressed) und optional ein
  // "+"-Popover (.popover), dessen Emoji-Buttons [data-reaction-add="<emoji>"] tragen.
  // Klick auf einen Chip togglet die eigene Reaktion (Zähler ±1, aria-pressed -> Accent-Look
  // aus .btn[aria-pressed] in components.css); FÄLLT DER ZÄHLER AUF 0, verschwindet der Chip
  // (Chat-Konvention: eine Reaktion ohne Stimmen wird nicht mehr angezeigt). Ein Emoji im
  // Popover erhöht einen vorhandenen Chip (nur einmal je Nutzer) bzw. legt einen neuen an
  // (Zähler 1, aria-pressed) und schließt das Popover. Ohne JS bleibt das statische Markup
  // gültig (Chips sichtbar, nur ohne Klick-Verhalten).
  function wireReactions(box) {
    if (box.dataset.c22ReactWired) return;
    box.dataset.c22ReactWired = '1';
    // Bestand normalisieren: Chips mit Zähler 1 zeigen nur das Emoji
    box.querySelectorAll('[data-reaction] [data-reaction-count]').forEach(function (c) {
      c.hidden = (parseInt(c.textContent, 10) || 0) <= 1;
    });

    function reactionLabel(emoji, n) {
      return emoji + ', ' + n + (n === 1 ? ' Reaktion' : ' Reaktionen');
    }
    function countOf(chip) {
      var c = chip.querySelector('[data-reaction-count]');
      return c ? (parseInt(c.textContent, 10) || 0) : 0;
    }
    function setCount(chip, n) {
      var c = chip.querySelector('[data-reaction-count]');
      if (c) {
        c.textContent = n;
        c.hidden = n <= 1;   // bei EINER Reaktion nur das Emoji, die Zahl erst ab zwei (PO)
      }
      chip.setAttribute('aria-label', reactionLabel(chip.dataset.reaction, n));
    }
    function chipFor(emoji) {   // Emoji-Vergleich statt Attribut-Selektor (spart CSS.escape)
      var found = null;
      box.querySelectorAll('[data-reaction]').forEach(function (ch) {
        if (ch.dataset.reaction === emoji) found = ch;
      });
      return found;
    }
    function makeChip(emoji, n) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn';
      b.setAttribute('data-variant', 'outline');
      b.setAttribute('data-size', 'xs');
      b.setAttribute('data-reaction', emoji);
      b.setAttribute('aria-pressed', 'true');
      b.setAttribute('aria-label', reactionLabel(emoji, n));
      var e = document.createElement('span');
      e.setAttribute('aria-hidden', 'true');
      e.textContent = emoji;
      var c = document.createElement('span');
      c.setAttribute('data-reaction-count', '');
      c.textContent = n;
      c.hidden = n <= 1;
      b.appendChild(e); b.appendChild(c);
      return b;
    }
    function closePicker() {
      var picker = box.querySelector('.popover');
      if (!picker) return;
      var trigger = picker.querySelector(':scope > button');
      var panel = picker.querySelector(':scope > [data-popover]');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
      if (panel) panel.setAttribute('aria-hidden', 'true');
    }
    function toggleOwn(chip) {
      var pressed = chip.getAttribute('aria-pressed') === 'true';
      var n = countOf(chip) + (pressed ? -1 : 1);
      chip.setAttribute('aria-pressed', pressed ? 'false' : 'true');
      if (n <= 0) chip.remove();          // Zähler 0 -> Chip verschwindet
      else setCount(chip, n);
    }
    function addReaction(emoji) {
      var chip = chipFor(emoji);
      if (chip) {
        if (chip.getAttribute('aria-pressed') !== 'true') {   // je Nutzer nur einmal zählen
          chip.setAttribute('aria-pressed', 'true');
          setCount(chip, countOf(chip) + 1);
        }
      } else {
        box.appendChild(makeChip(emoji, 1));   // Chips stehen IMMER rechts vom React-Knopf (PO)
      }
    }

    box.addEventListener('click', function (e) {
      var add = e.target.closest('[data-reaction-add]');
      if (add && box.contains(add)) { addReaction(add.getAttribute('data-reaction-add')); closePicker(); return; }
      var chip = e.target.closest('[data-reaction]');
      if (chip && box.contains(chip)) toggleOwn(chip);
    });
  }

  // ---- Modal-Entry entzerren --------------------------------------------------
  // showModal() für C22-Modals (.dialog/.alert-dialog/.drawer) so patchen, dass der Browser
  // erst EINEN Frame im Startzustand committet (Klasse c22-open-hold, Transition aus) und der
  // Übergang dann regulär startet — dasselbe Doppel-rAF-Muster wie Material Components und
  // Headless UI. Grund + Zustände: components.css (Entry-Jank-Gegenmittel).
  if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype._c22Patched) {
    HTMLDialogElement.prototype._c22Patched = true;
    var c22OrigShowModal = HTMLDialogElement.prototype.showModal;
    HTMLDialogElement.prototype.showModal = function () {
      var el = this;
      if (!el.open && el.matches('.dialog, .alert-dialog, .drawer')) {
        el.classList.add('c22-open-hold');
        c22OrigShowModal.call(el);
        requestAnimationFrame(function () {
          requestAnimationFrame(function () { el.classList.remove('c22-open-hold'); });
        });
      } else {
        c22OrigShowModal.call(el);
      }
    };
  }

  function init(root) {
    wirePhIcons(root);
    // Drawer: Exit OHNE Scroll-Sperre. Basecoats drawer.js überschreibt close() mit einer
    // JS-Choreografie (data-closing setzen, ~Animationsdauer warten, DANN nativ schließen) —
    // der Drawer bleibt so die ganze Ausfahranimation modal, die Seite inert/scrollgesperrt.
    // Das native close() reicht: transition-discrete + `overlay` (im transition-all der
    // Vendor-CSS enthalten) halten Element und ::backdrop bis zum Animationsende sichtbar im
    // Top Layer, modal ist es aber sofort nicht mehr — Scroll ist ab Klick frei (wie beim
    // Dialog, der es genau so macht). VERSIEGELT statt zugewiesen: Basecoat initialisiert
    // NACH uns und würde eine einfache Zuweisung wieder überschreiben; auf die nicht
    // beschreibbare Property prallt seine Zuweisung still ab (Bundle ist nicht strict,
    // Init zudem in try/catch) — alle übrigen Basecoat-Handler (Esc, Backdrop-Klick)
    // rufen weiter d.close() auf und landen so beim nativen close.
    (root || document).querySelectorAll('dialog.drawer').forEach(function (d) {
      if (Object.getOwnPropertyDescriptor(d, 'close')) return;   // schon versiegelt/gesetzt
      Object.defineProperty(d, 'close', {
        value: HTMLDialogElement.prototype.close,
        writable: false,
        configurable: false,
      });
    });
    (root || document).querySelectorAll('.context-menu').forEach(wireContextMenu);
    (root || document).querySelectorAll('[data-calendar]').forEach(wireCalendar);
    (root || document).querySelectorAll('[data-clock]').forEach(wireClock);
    (root || document).querySelectorAll('[data-time-stepper]').forEach(wireTimeStepper);
    (root || document).querySelectorAll('[data-date-input]').forEach(wireDateInput);
    (root || document).querySelectorAll('.input-group').forEach(wireAffixStrip);
    (root || document).querySelectorAll('[data-password-toggle]').forEach(wirePasswordToggle);
    (root || document).querySelectorAll('[data-clear]').forEach(wireClearButton);
    (root || document).querySelectorAll('[data-number-step]').forEach(wireNumberStep);
    (root || document).querySelectorAll('.input-otp-slot').forEach(wireOtp);
    (root || document).querySelectorAll('[data-pagination]').forEach(wirePagination);
    (root || document).querySelectorAll("[role='menu']").forEach(wireMenuChecks);
    (root || document).querySelectorAll('[data-datatable]').forEach(wireDataTable);
    (root || document).querySelectorAll('.table-container :is(.dropdown-menu, .popover)').forEach(wireTableMenu);
    (root || document).querySelectorAll('[data-filter-combo]').forEach(wireFilterCombo);
    (root || document).querySelectorAll('[data-slider-multi]').forEach(wireMultiSlider);
    (root || document).querySelectorAll('[data-mute]').forEach(wireMute);
    (root || document).querySelectorAll('[data-feedback]').forEach(wireFeedback);
    (root || document).querySelectorAll('[data-message-delete]').forEach(wireMessageDelete);
    (root || document).querySelectorAll('[data-resize-handle]').forEach(wireResizeHandle);
    (root || document).querySelectorAll('[data-carousel]').forEach(wireCarousel);
    (root || document).querySelectorAll('[data-chart]').forEach(wireChart);
    (root || document).querySelectorAll('[data-tab-hash]').forEach(wireTabHash);
    (root || document).querySelectorAll('[data-scroll-fade]').forEach(wireScrollFade);
    (root || document).querySelectorAll('[data-nav-select]').forEach(wireNavSelect);
    (root || document).querySelectorAll('[data-edit-table]').forEach(wireEditTable);
    (root || document).querySelectorAll('[data-char-count]').forEach(wireCharCount);
    (root || document).querySelectorAll('[data-copy]').forEach(wireCopy);
    (root || document).querySelectorAll('[data-reactions]').forEach(wireReactions);
    wireGlobals();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else {
    init();
  }
  window.C22 = window.C22 || {};
  window.C22.init = init;             // Context-Menu + Kalender + Carousel (für dynamisch nachgeladenes Markup)
  window.C22.initContextMenus = init;
  window.C22.wireChart = wireChart;   // einzelnes [data-chart]-Element gezielt verdrahten
  window.C22.phIcon = phIcon;         // Phosphor-SVG als String: phIcon(name, gewicht)
})();

/* C22: Command-Palette ohne initiale Vorauswahl (weder eingebettet noch im Popover/Dialog).
   basecoat markiert beim Init IMMER den ersten Treffer aktiv (das Enter-Ziel einer Palette) — das
   wirkt wie eine feste Auswahl, auch in einer frisch geöffneten Palette. Hier wird diese INITIALE
   Markierung entfernt; Maus/Tastatur setzen sie bei der ersten Interaktion normal wieder (basecoat
   mousemove/keydown). Capture, weil basecoat:initialized nicht bubbelt. */
document.addEventListener('basecoat:initialized', function (e) {
  var el = e.target;
  if (!el || !el.classList || !el.classList.contains('command')) return;
  var active = el.querySelector('[role="menuitem"].active');
  if (!active) return;
  active.classList.remove('active');
  var input = el.querySelector('header input');
  if (input) input.removeAttribute('aria-activedescendant');
}, true);

/* C22: Dropdown-Panel in SCROLL-CONTAINERN (data-popover-fixed am .dropdown-menu).
   overflow-Container clippen die absolut positionierten Panels; das Muster hier:
   Panel liegt FIXED (CSS in components.css) und bekommt seine Koordinaten SYNCHRON
   VOR basecoats Öffnen gesetzt (capture-Click) sowie einmal beim Verdrahten — die
   Koordinaten sind bewusst NICHT Teil der Öffnungs-Transition, sonst fliegt das
   Panel beim ERSTEN Öffnen von seiner Standardposition quer über den Schirm.
   Praxis-Fund 2026-07-20/21 (Optionen-Menü in einer scrollenden Sidebar). */
(function () {
  function position(wrapper) {
    var trigger = wrapper.querySelector(':scope > button, :scope > [aria-haspopup]');
    var panel = wrapper.querySelector(':scope > [data-popover]');
    if (!trigger || !panel) return;
    var r = trigger.getBoundingClientRect();
    var luft = 4;
    var side = panel.getAttribute('data-side') || 'bottom';
    if (side === 'right') {
      panel.style.left = (r.right + luft) + 'px';
      panel.style.top = Math.max(8, Math.min(r.top, window.innerHeight - 280)) + 'px';
    } else if (side === 'left') {
      panel.style.right = (window.innerWidth - r.left + luft) + 'px';
      panel.style.top = Math.max(8, Math.min(r.top, window.innerHeight - 280)) + 'px';
    } else {
      var align = panel.getAttribute('data-align') || 'start';
      if (align === 'end') panel.style.right = (window.innerWidth - r.right) + 'px';
      else panel.style.left = r.left + 'px';
      panel.style.top = (r.bottom + luft) + 'px';
    }
  }
  function wire(root) {
    var basis = root && root.querySelectorAll ? root : document;
    basis.querySelectorAll('.dropdown-menu[data-popover-fixed]').forEach(position);
  }
  document.addEventListener('click', function (e) {
    var wrapper = e.target.closest && e.target.closest('.dropdown-menu[data-popover-fixed]');
    if (wrapper) position(wrapper);
  }, true);
  window.addEventListener('resize', function () { wire(document); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { wire(document); });
  else wire(document);
  new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      Array.prototype.forEach.call(m.addedNodes, function (n) {
        if (n.nodeType === 1) wire(n);
      });
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
})();

/* ============================================================================
 * TOC / Scrollspy — welcher Abschnitt gerade gelesen wird
 *
 * Warum eigenes JS: Basecoat hat kein Inhaltsverzeichnis, und die Galerie brauchte genau das
 * (links markiert, wo man im Inhalt steht). Die Component macht daraus einen Baustein statt
 * einer Galerie-Sonderlocke.
 *
 * Markup-Vertrag (siehe components/toc.html):
 *   <nav class="toc" data-toc="#inhalt" data-marker="bar">
 *     <a href="#start" data-toc-title>Seitentitel</a>   ← aktiv, solange man im KOPF steht
 *     <a href="#abschnitt-1">…</a>                      ← data-level="2|3" rückt ein
 *   </nav>
 * Der aktive Eintrag trägt `aria-current="true"` — die Markierung selbst ist CSS-Sache
 * (`data-marker`), damit eine neue Markierungsart keine JS-Änderung braucht.
 *
 * Gemessen wird NICHT reine Sichtbarkeit (ein langer Abschnitt ist minutenlang sichtbar,
 * mehrere kurze gleichzeitig), sondern die klassische Lesemarke: aktiv ist der letzte
 * Abschnitt, dessen Oberkante die Marke passiert hat. Beobachtet wird der scrollende
 * Container — in der Galerie scrollt `main`, nicht das Fenster.
 * ========================================================================== */
(function () {
  'use strict';

  function scrollElter(el) {
    // Beim ELEMENT SELBST anfangen, nicht beim Elternteil: in der Galerie scrollt `main`
    // selbst, in den Beispielen der Inhalts-Div selbst. Die erste Fassung begann bei
    // `parentElement`, fand deshalb nichts und hängte den Listener an `window` — das dort
    // nie scrollt. Ergebnis: die Markierung stand still, obwohl alles andere stimmte.
    for (var p = el; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
      var s = getComputedStyle(p).overflowY;
      if ((s === 'auto' || s === 'scroll') && p.scrollHeight > p.clientHeight + 1) return p;
    }
    return null;
  }

  function wireToc(toc) {
    if (toc.dataset.tocFertig) return;
    toc.dataset.tocFertig = '1';

    var links = Array.prototype.slice.call(toc.querySelectorAll('a[href^="#"]'));
    if (!links.length) return;

    var titelLink = toc.querySelector('[data-toc-title]');
    var ziele = links.map(function (a) {
      var id = a.getAttribute('href').slice(1);
      return { a: a, el: id ? document.getElementById(id) : null, titel: a.hasAttribute('data-toc-title') };
    }).filter(function (z) { return z.el || z.titel; });

    var inhalt = toc.dataset.toc ? document.querySelector(toc.dataset.toc) : null;
    var behaelter = scrollElter(inhalt || (ziele[0] && ziele[0].el) || toc);

    // Hamburger: die Linien SIND das Inhaltsverzeichnis. Ihre Anzahl kommt aus den Einträgen,
    // nicht aus der Gewohnheit „drei Striche". Bei langen Verzeichnissen fasst eine Linie
    // mehrere Einträge zusammen (data-max-lines), sonst wären es fünfzig Haarlinien.
    // Beim Hamburger sitzt die Linien-Box im AUSLÖSER, das Verzeichnis selbst im Popover —
    // sie ist also kein Kind des Navs. Deshalb erst im Nav suchen, dann in der Dropdown-Hülle.
    var huelle = toc.closest('.dropdown-menu') || toc.parentElement;
    var linienBox = toc.querySelector('[data-toc-lines]')
      || (huelle && huelle.querySelector('[data-toc-lines]'));
    var maxLinien = parseInt(toc.dataset.maxLines || '7', 10);
    var eintraege = ziele.filter(function (z) { return !z.titel; });
    var proLinie = Math.max(1, Math.ceil(eintraege.length / maxLinien));
    var linien = [];
    if (linienBox) {
      linienBox.textContent = '';
      var anzahl = Math.ceil(eintraege.length / proLinie);
      for (var i = 0; i < anzahl; i++) {
        var strich = document.createElement('span');
        strich.setAttribute('data-toc-line', '');
        linienBox.appendChild(strich);
        linien.push(strich);
      }
      linienBox.setAttribute('data-lines', String(anzahl));
    }

    function markiere(aktiv) {
      ziele.forEach(function (z) {
        if (z.a === aktiv) z.a.setAttribute('aria-current', 'true');
        else z.a.removeAttribute('aria-current');
      });
      if (!linien.length) return;
      var idx = -1;
      eintraege.forEach(function (z, i) { if (z.a === aktiv) idx = i; });
      var treffer = idx < 0 ? -1 : Math.floor(idx / proLinie);
      linien.forEach(function (s, i) {
        if (i === treffer) s.setAttribute('data-active', '');
        else s.removeAttribute('data-active');
      });
    }

    function marke() {
      // Lesemarke: ein Stück unter der Oberkante des Sichtbereichs — nicht am Rand, sonst
      // schaltet der Eintrag schon, wenn der Abschnitt nur mit dem Rand hereinschaut.
      var r = behaelter ? behaelter.getBoundingClientRect().top : 0;
      var h = behaelter ? behaelter.clientHeight : window.innerHeight;
      return r + Math.min(160, h * 0.28);
    }

    function pruefe() {
      var m = marke();
      var aktiv = null;
      eintraege.forEach(function (z) {
        if (z.el && z.el.getBoundingClientRect().top <= m) aktiv = z.a;
      });
      // Noch im Kopfbereich: dann gilt der Seitentitel (falls es einen Eintrag dafür gibt).
      if (!aktiv && titelLink) aktiv = titelLink;
      if (!aktiv && eintraege.length) aktiv = eintraege[0].a;
      markiere(aktiv);
    }

    var geplant = false;
    function anstossen() {
      if (geplant) return;
      geplant = true;
      requestAnimationFrame(function () { geplant = false; pruefe(); });
    }

    (behaelter || window).addEventListener('scroll', anstossen, { passive: true });
    // Netz für alles andere: Scroll-Ereignisse einzelner Container BUBBELN NICHT, sind aber
    // in der Capture-Phase am Dokument zu sehen. Damit funktionieren beliebig viele
    // Verzeichnisse auf einer Seite, jedes mit eigenem Inhaltsbereich — und auch ein
    // Container, der erst später überhaupt scrollbar wird (nachgeladener Inhalt).
    document.addEventListener('scroll', anstossen, { capture: true, passive: true });
    window.addEventListener('resize', anstossen);
    // Wird die Seite MIT Anker geöffnet, springt der Browser erst nach diesem Skript — ohne
    // diesen zweiten Blick stünde die Markierung auf dem ersten Abschnitt, obwohl man mitten
    // im Dokument gelandet ist.
    window.addEventListener('load', anstossen);
    pruefe();

    // Ein Klick soll nicht auf das Scroll-Ereignis warten müssen.
    links.forEach(function (a) {
      a.addEventListener('click', function () { markiere(a); setTimeout(pruefe, 300); });
    });
  }

  function wireAlle(root) {
    var basis = root && root.querySelectorAll ? root : document;
    // NUR mit `data-toc` — die Lesemarke ist Opt-in. Sonst griffe sie auch nach
    // Verzeichnissen, die absichtlich einen festen Zustand zeigen (Galerie-Beispiele), und
    // überschriebe deren `aria-current` mit der Lesemarke der umgebenden Seite.
    basis.querySelectorAll('.toc[data-toc]').forEach(wireToc);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { wireAlle(document); });
  } else {
    wireAlle(document);
  }
  new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      Array.prototype.forEach.call(m.addedNodes, function (n) {
        if (n.nodeType === 1) wireAlle(n);
      });
    });
  }).observe(document.documentElement, { childList: true, subtree: true });

  window.C22 = window.C22 || {};
  window.C22.initTocs = wireAlle;
})();
