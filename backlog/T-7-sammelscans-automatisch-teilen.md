---
type: Task
title: Sammelscans automatisch teilen
status: offen
id: T-7
milestone: M-1
tags: [split, ocr, panel, klassifikation]
created: '2026-11-11'
---
# T-7 — Sammelscans automatisch teilen

**Anlass (PO 2026-11-11):** Ein Scanner legt ganze Stapel als ein PDF mit dem Tag „Sammelscan“ ab. Vorerst teilt ein Mensch den Stapel; paperlaiss soll das übernehmen.

**Idee:**
- Trennvorschlag je Seite aus dem OCR-Text: neuer Absender bzw. Briefkopf, „Seite 1 von N“, Datum, Anrede, Seitenzählung bricht ab.
- Im Panel: Vorschlag als Seitengruppen („S. 1–2 Stadtwerke, S. 3 Arzt …“), ein Mensch bestätigt oder verschiebt Trennstellen.
- Ausführen über die Paperless-API `bulk_edit` mit `split` (Seitengruppen, `delete_originals`); die Teile laufen danach normal durch Routing und Klassifizierung.
- Regeln aus den ersten Handteilungen ableiten und als Testfälle für `eval.py` festhalten.

**Dazu nötig:**
- Ein konfigurierbarer Skip-Tag: Dokumente mit „Sammelscan“ klassifiziert die KI erst nach dem Teilen. Heute läuft sie am ganzen Stapel, und die Teile erben beim Split den Marker-Tag. Ohne Abnehmen des Markers würden sie übersprungen.
- Prüfen, welche Tags, Rechte und Felder Paperless beim Split vererbt.

**Alternative:** Paperless teilt nativ an Trennblättern mit Barcode (PATCH-T), das geht ohne Raten, braucht aber Trennblätter im Stapel.
