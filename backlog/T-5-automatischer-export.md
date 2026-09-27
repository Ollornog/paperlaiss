---
id: T-5
type: Task
title: Automatischer Export nach Regeln (Filter, Turnus, Auslöser)
status: offen
milestone: M-1
tags: [export, knoepfe, automatik]
created: 2026-09-27
---

# T-5 — Automatischer Export nach Regeln

Wunsch aus dem Betrieb: Exporte nicht nur von Hand über den Knopf, sondern als **Regel**, die
man einmal anlegt — mit festen **Filtern** (Korrespondent, Typ, Tags, Zeitraum, Feldwerte) und
einem **Auslöser**: fester Turnus (täglich, monatlich, Quartalsende) oder ein Ereignis
(Dokument angekommen, Tag gesetzt).

**Baut auf dem Export-Knopf auf:** dieselben Varianten (ein PDF mit Verzeichnis oder einzeln mit
Namensvorlage, ZIP), dieselben Grenzen, dieselbe Logik in `panel/exportlogik.py`.

**Vor dem Bau zu klären (Betreiber):**

1. **Wohin geht das Ergebnis?** Ein Knopf-Export ist ein Download und nur kurz abrufbar
   (`EXPORT_AUFBEWAHRUNG_MIN`). Eine Regel braucht ein festes Ziel: Ordner (lokal/WebDAV), Mail
   oder eine Liste im Panel mit längerer Aufbewahrung.
2. **Filter:** eigene Felder im Panel oder eine gespeicherte Ansicht aus Paperless übernehmen
   (dann pflegt man den Filter dort, wo man ihn ohnehin sieht).
3. **Wessen Rechte?** Ein Knopf-Export prüft die Leserechte des klickenden Nutzers. Eine Regel
   läuft ohne Sitzung — sie braucht einen festen Eigentümer, dessen Rechte gelten.
4. **Nur Neues oder alles?** Bei Turnus-Exporten: nur, was seit dem letzten Lauf dazukam, oder
   jedes Mal der ganze Filter.

**Zeitpunkte** in der Zeitzone der Installation (nicht UTC). **Fertig, wenn** eine Regel angelegt,
im Panel sichtbar, abschaltbar ist und ein Lauf nachvollziehbar protokolliert wird (was, wie
viele, wohin, Fehler).
