"""Seitengerüst des Panels in C22-Markup: Hülle mit Seitenleiste, Kopf, Kennzahlen, Dialog.

Das Aussehen kommt aus **C22** (Tokens + kanonisches HTML + Basecoat-Klassen), vendort unter
`static/c22/` (`scripts/vendor-c22.sh`). Hier stehen nur dünne Adapter; die Vorlagen sind die
C22-Blöcke `navigation/app-shell.html` und `full-page/dashboard.html`.

**Nur Klassen, die C22 selbst benutzt.** C22 kompiliert Tailwind gegen die eigenen Quellen; eine
Klasse, die dort nicht vorkommt, fehlt im Pack und tut still nichts. `tests/test_c22_klassen.py`
prüft jede Klasse und jede Variante im Panel gegen das vendorte Stylesheet.

Warum eine eigene Datei: Routen (`app.py`), Seiteninhalte (`seiten.py`) und das Gerüst ändern sich
aus verschiedenen Gründen. Ein Redesign fasst idealerweise nur diese Datei und C22 an.
"""
from __future__ import annotations

import html

# Lucide-Pfade, wörtlich aus den C22-Komponenten (gleiche Strichstärke, gleicher Rahmen).
_ICONS = {
    'settings-2': '<path d="M20 7h-9"/><path d="M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>',
    'send': '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    'file-plus': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M9 15h6"/><path d="M12 12v6"/>',
    'message-square': '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    'layout-dashboard': '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
    'list': '<line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/>',
    'image': '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
    'eye': '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    'cloud-upload': '<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M12 12v9"/><path d="m16 16-4-4-4 4"/>',
    'badge-check': '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><path d="m9 12 2 2 4-4"/>',
    'external-link': '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    'arrow-down': '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    'bot': '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    'chart-column': '<path d="M3 3v18h18"/><rect width="3" height="6" x="7" y="12"/><rect width="3" height="10" x="12" y="8"/><rect width="3" height="14" x="17" y="4"/>',
    'chevron-left': '<path d="m15 18-6-6 6-6"/>',
    'chevron-right': '<path d="m9 18 6-6-6-6"/>',
    'circle-alert': '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
    'circle-check': '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    'file-text': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M9 15h6"/><path d="M9 11h6"/>',
    'funnel-x': '<path d="M12.531 3H2a1 1 0 0 0-.8 1.6l6.6 8.8a1 1 0 0 1 .2.6v6.09a1 1 0 0 0 .553.895l2 1A1 1 0 0 0 12 21.09V14a1 1 0 0 1 .2-.6l1.62-2.16"/><path d="m17 17 5-5"/><path d="m22 17-5-5"/>',
    'git-branch': '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    'inbox': '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    'info': '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    'log-out': '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
    'panel-left': '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    'pencil': '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    'refresh-ccw': '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
    'rotate-ccw': '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    'save': '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/>',
    'settings': '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    'triangle-alert': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    'x': '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'
}

# Navigation: gleiche Leiste auf jeder Seite, die aktive ist über aria-current hinterlegt.
NAVIGATION: list[tuple[str, str, str]] = [
    ("Aktivität", "/", "chart-column"),
    ("Ablauf & Prompt", "/ablauf", "git-branch"),
    ("Einstellungen", "/einstellungen", "settings"),
    ("Info", "/info", "info"),
]


def e(wert: object) -> str:
    """HTML-sicher ausgeben; `None` wird zum Gedankenstrich."""
    return html.escape(str(wert if wert is not None else "—"))


def symbol(name: str, klasse: str = "") -> str:
    """Ein Lucide-Symbol im C22-Rahmen. Ohne `klasse` nur innerhalb eines `.btn` benutzen."""
    k = f' class="{klasse}"' if klasse else ""
    return (f'<svg data-icon-lu="{name}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round"{k}>{_ICONS[name]}</svg>')


def rahmen(titel: str, koerper: str) -> str:
    """Das HTML-Dokument: Stylesheet und Verhaltensschicht aus dem vendorten C22."""
    return (
        '<!doctype html><html lang="de" class="dark"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{e(titel)} — paperlaiss</title><link rel="icon" href="/logo.png">'
        '<link rel="stylesheet" href="/static/c22/css/c22.css">'
        '<script src="/static/c22/js/basecoat.all.min.js" defer></script>'
        '<script src="/static/c22/js/c22.js" defer></script>'
        f'</head><body>{koerper}</body></html>'
    )


def seite(titel: str, aktiv: str, inhalt: str, abmelden: bool = False) -> str:
    """Vollständige Seite: Titelleiste mit Navigation, darunter der Inhalt.

    Die Navigation steht in der Titelleiste (C22 `navigation/app-shell.html`, Nav-Punkte als
    `.btn` ghost/sm), keine Seitenleiste — vier Seiten brauchen keine. Titelleiste und Inhalt
    stehen in derselben Spur (`max-w-5xl`), damit sie auf breiten Schirmen bündig bleiben. Die aktive Seite ist
    hinterlegt (`bg-accent`) und semantisch markiert (`aria-current`).
    """
    def punkt(name: str, pfad: str, sym: str) -> str:
        if pfad == aktiv:
            return (f'<a href="{e(pfad)}" class="btn bg-accent text-accent-foreground" data-variant="ghost" '
                    f'data-size="sm" aria-current="page">{symbol(sym)}{e(name)}</a>')
        return f'<a href="{e(pfad)}" class="btn" data-variant="ghost" data-size="sm">{symbol(sym)}{e(name)}</a>'

    punkte = "".join(punkt(*n) for n in NAVIGATION)
    raus = (f'<a class="btn" data-variant="outline" data-size="sm" href="/auth/logout">'
            f'{symbol("log-out")}Abmelden</a>' if abmelden else "")
    koerper = f"""<div class="flex h-screen w-full flex-col bg-background text-foreground">
  <header class="shrink-0 border-b bg-card">
    <div class="mx-auto flex w-full max-w-5xl items-center gap-3 px-4 py-2">
      <a href="/" class="flex items-center gap-2 text-base font-bold">
        <img src="/logo.png" alt="" width="28" height="28"> paperlaiss
      </a>
      <nav class="ms-2 flex items-center gap-1" aria-label="Hauptbereiche">{punkte}</nav>
      <div class="ms-auto flex items-center gap-3">{raus}</div>
    </div>
  </header>
  <main class="flex-1 overflow-y-auto text-sm"><div class="mx-auto w-full max-w-5xl p-6">{inhalt}</div></main>
</div>"""
    return rahmen(titel, koerper)


def kopf(titel: str, beschreibung: str = "", aktionen: str = "") -> str:
    """Seitenkopf: was man hier sieht, und was man hier tun kann."""
    text = f'<p class="text-muted-foreground text-sm">{e(beschreibung)}</p>' if beschreibung else ""
    # Klebt oben im Inhaltsbereich (sticky): Titel und Aktionen wie „Speichern" scrollen nicht mit.
    # -mx-6/-mt-6 + px-6/pt-6 ziehen die Leiste bis an die Ränder der Spur, damit darunter
    # scrollender Inhalt nicht seitlich durchscheint.
    return (f'<div class="sticky top-0 z-10 -mx-6 -mt-6 flex flex-wrap items-end justify-between gap-3 '
            f'border-b bg-background px-6 py-6">'
            f'<div><h1 class="text-lg font-semibold tracking-tight">{e(titel)}</h1>{text}</div>'
            f'<div class="flex flex-wrap items-center gap-2">{aktionen}</div></div>'
            # Luft unter der Linie: Abstandshalter statt mb-8 — das steht nicht im C22-Pack.
            f'<div class="h-8" aria-hidden="true"></div>')


def abschnitt(titel: str, koerper: str, aktionen: str = "", kennung: str = "") -> str:
    """Kartenabschnitt mit Titelzeile und optionalen Aktionen rechts."""
    k = f' id="{e(kennung)}"' if kennung else ""
    return (f'<div class="card mt-6" data-size="sm"{k}>'
            f'<header class="flex flex-wrap items-center justify-between gap-2"><h2>{e(titel)}</h2>'
            f'<div class="flex flex-wrap items-center gap-2">{aktionen}</div></header>'
            f'<section>{koerper}</section></div>')


def dialog(kennung: str, titel: str, koerper: str, fuss: str = "", breit: bool = True) -> str:
    """Modaler Dialog nach `c22/components/dialog.html`; Inhalt füllt die Seite per Skript."""
    weite = ' class="md:max-w-4xl"' if breit else ""
    return (f'<dialog id="{e(kennung)}" class="dialog" aria-labelledby="{e(kennung)}-titel" '
            f'onclick="if (event.target === this) this.close()">'
            f'<div{weite}><header><h2 id="{e(kennung)}-titel">{e(titel)}</h2></header>'
            # min-h-0 + overflow-y-auto: C22 begrenzt den Dialog auf die Fensterhöhe, der Inhalt
            # selbst scrollt aber nicht — langer Inhalt wäre sonst abgeschnitten.
            # p-1: ein Scrollbereich schneidet ab, was über seinen Rand ragt — sonst fehlte der Kartenrand.
            f'<section class="min-h-0 overflow-y-auto p-1">{koerper}</section>'
            + (f'<footer>{fuss}</footer>' if fuss else "") +
            f'<button type="button" class="btn btn-close" data-variant="ghost" aria-label="Schließen" '
            f'onclick="this.closest(\'dialog\').close()">{symbol("x")}</button></div></dialog>')
