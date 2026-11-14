---
type: Task
title: 'Garantie in Jahren, Ende aus dem Code'
status: erledigt
id: T-16
milestone: M-1
tags: [felder, garantie, abgleich]
created: '2026-11-14'
---
# T-16 — Garantie in Jahren, Ende aus dem Code

**Anlass (2026-11-14):** Ein Betreiber will 30 Tage vor Ablauf einer Garantie erinnert werden. Ein Datumsfeld „Garantie
bis“ pflegte niemand von Hand, und die KI setzte es auch bei Versicherungen (Garantiezeit eines Vertrags), wo es nichts
mit einem Kauf zu tun hat. Gewünscht: eine Zahl „Garantie in Jahren“, das Ende aus Belegdatum + Jahre, eine Erinnerung
über einen zeitgesteuerten Paperless-Workflow.

**Umsetzung:**
1. `garantie_felder`: wirkt nur mit beiden Feldern (Jahre als Zahl, Ende als Datum) und `garantie_aktiv`.
2. KI: Hinweis an der Feldzeile der Jahre (Standard `garantie_standard_jahre`, längere Garantie aus dem Text, nichts bei
   Dienstleistung, Abo, Versicherung, Vertrag); Vorschlag nur bei `garantie_typen` (`feldvorschlag_verwerfen`).
3. Ende: nie von der KI (`skip_fids`), sondern `garantie_ende` aus dem Datum, das am Dokument stehen wird, und den
   Jahren, die geschrieben werden (`garantie_code_feld`, auch in den Reparaturrunden); ohne Jahre entfernt.
4. `CLASSIFY_GARANTIE=1`: `garantie_plan` über alle Dokumente mit einem der Felder, Massenbearbeitung je Dokument,
   Fehler gesammelt (Exit 1).

**Messung:** 15 Mutanten rot, `check.sh` zweimal grün. Bestand der Installation: zwei Kaufbelege (1 Jahr, 6 Monate)
stimmen mit dem berechneten Ende überein; drei falsch gesetzte Enden an Versicherungsunterlagen sind entfernt.
