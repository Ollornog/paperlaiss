---
type: Task
title: 'Korrektur-Log: was Menschen nach der KI geändert haben'
status: erledigt
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

**Stand 2026-10-14 — Stufe 1 gebaut:** Panel-Seite „Nacharbeit“ mit Quote je Feld, Korrespondent, Typ und
Woche sowie der Fallliste (`panel/nacharbeit.py`, Test `tests/test_nacharbeit.py`). Entschieden:
- Abholen beim Öffnen der Seite (älter als 30 min) oder per Knopf, kein Zeitplan; Ergebnis in `nacharbeit.json`.
- Tags: nur das Entfernen eines Tags, den die KI gesetzt hat, ist eine Korrektur; Workflow-Tags zählen nicht.
- Felder, die die KI nicht gesetzt hat (Bezahlt-Am), zählen nicht. Leer → Wert heißt „ergänzt“, Wert → leer „geleert“.

**Stand 2026-10-15 — erledigt:** Export als Sollliste für `eval.py` (Knopf „Sollliste“, `/api/nacharbeit/sollliste`, `nacharbeit.sollliste`). Je Dokument der jüngste Lauf; nur Korrekturen an Korrespondent, Typ oder Datum; nicht korrigierter Korrespondent/Typ gilt als bestätigt.
