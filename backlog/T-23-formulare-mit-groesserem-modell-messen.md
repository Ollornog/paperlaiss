---
type: Task
title: 'Formulare mit einem größeren Modell gegen die Sollliste messen'
status: offen
id: T-23
milestone: M-1
tags: [ki, eval]
created: '2026-11-19'
---
# T-23 — Formulare mit einem größeren Modell gegen die Sollliste messen

**Anlass:** T-9 Punkt 9. Bei Formularen (Lohnsteuerbescheinigung, Meldebescheinigung zur Sozialversicherung,
Lohnabrechnung) verwechselte das kleine Modell den Korrespondenten (Arbeitgeber gegen Einzugsstelle oder die eigene
Person) und den Typ. Offen ist, ob ein größeres Modell (z. B. `mistral-medium-2604`) das spürbar besser macht und was es
kostet.

**Vorgehen:**
- Sollliste aus einer Nacharbeit nehmen (Panel *Nacharbeit* → *Sollliste*; seit T-9 zählen auch Massenbearbeitungen),
  nur die Formulare.
- `eval.py --wie-import --wiederholen 3` einmal mit dem gepinnten kleinen Modell, einmal mit dem größeren (Config-Kopie
  mit anderem `model`), Quoten je Feld und Kosten je Dokument (`NUTZUNG` im Trace) gegenüberstellen.
- Zuerst mit der Beispielkonfiguration (`deploy/beispiel-config-haushalt.json`) messen: Typbeschreibungen könnten den
  Unterschied schon schließen.

**Voraussetzung:** eine Installation mit echten Formularen und Einverständnis der Besitzer; nicht im Repo.
