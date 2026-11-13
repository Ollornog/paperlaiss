---
type: Task
title: 'Lohnabrechnungs-Datum im Code statt durch die KI, USt-ID nur aus dem Text'
status: erledigt
id: T-14
milestone: M-1
tags: [datum, stammdaten, ki]
created: '2026-11-13'
---
# T-14 — Lohnabrechnungs-Datum im Code statt durch die KI, USt-ID nur aus dem Text

**Anlass (2026-11-13):** Entscheid der Installation: Lohnabrechnungen ohne Ausstellungsdatum tragen den letzten Tag
des Abrechnungsmonats. Die Typbeschreibung reichte nicht: Die KI schlug in 43 von 67 Abrechnungen den Monatsersten vor,
bei Rückrechnungen den korrigierten Monat („Rückrechnung März 2022“ auf der Abrechnung Juni 2022). Dazu bekam jeder Brief
eines Arbeitgebers den Prüfhinweis „USt-ID gehört schon zu <Konzernmutter>“, obwohl die Briefe keine USt-ID tragen.

**Umsetzung:**
1. `monatsletzter_typen` (Vorgabe leer): Datum = letzter Tag des Abrechnungsmonats aus dem Text (`abrechnungsmonat`:
   Etikett „Abrechnungsmonat/-zeitraum“, auch als OCR-Spalte; „Monat/Jahr“; „Abrechnung für …“). Ein Datum mit
   Etikett bleibt (`ausstellungsdatum`); Daten aus Listen (Feiertag, Urlaub) zählen nicht.
2. USt-ID nur, wenn sie im Text steht (`kennung_im_text`): das Modell hatte sie aus dem Kandidaten im Prompt kopiert.

**Messung:** Sollliste der vierten Durchsicht (67 Abrechnungen): 19 → 67. Bestand (286 Abrechnungen einer Person): 132
Daten auf den Monatsletzten, kein Monat verschoben, Abrechnungen mit „wurde am … erstellt“ behalten ihr Datum.
