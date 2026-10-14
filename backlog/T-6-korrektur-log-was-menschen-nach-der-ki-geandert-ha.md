---
type: Task
title: 'Korrektur-Log: was Menschen nach der KI geändert haben'
status: offen
id: T-6
milestone: M-1
tags: [panel, auswertung, eval]
created: '2026-10-14'
---
# T-6 — Korrektur-Log: was Menschen nach der KI geändert haben

**Anlass (PO 2026-10-14):** Festhalten, was nach einem KI-Lauf von Hand geändert wurde (Titel, Korrespondent, Typ, Datum, Felder, Tags), um messen zu können, wie gut die Klassifizierung trifft.

**Idee:**
- Quelle ist die Paperless-Historie (`/api/documents/<id>/history/`, Audit-Log): Änderungen mit einem menschlichen Akteur **nach** dem Zeitstempel des letzten paperlaiss-Laufs (Trace `ts`), verglichen mit `writeback` im Trace.
- Im Panel ein Bereich „Korrekturen“ mit einer Liste je Dokument (Feld · KI-Wert → Menschen-Wert · wer · wann) und Kennzahlen je Feld bzw. Korrespondent: Trefferquote, häufigste Korrekturen.
- Optional ein Export als CSV oder als Sollliste für `eval.py`, damit Korrekturen zu Testfällen werden.

**Offen:**
- Abholen per Zeitplan oder beim Öffnen des Panels?
- Tags trennen: Workflow-Tags und Hand-Tags.
- Was zählt als Korrektur, was als Ergänzung (z. B. Bezahlt-Am)?
