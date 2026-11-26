---
type: Task
title: 'Austrian payslips: billing month as a word, month start as date, race on a new correspondent'
status: erledigt
id: T-33
milestone: M-1
created: '2026-11-26'
---
# T-33 — Austrian payslips: billing month as a word, month start as date, race on a new correspondent

Austrian payslips (Sage DPW) name the billing month only as a word plus year, or as period 13/14 of a year: kennzahlen() saw months with the same salary as duplicates and abrechnungsmonat() found no month. New installation rule: a payslip without a date of issue gets the FIRST day of the billing month (key renamed monatsletzter_typen to abrechnungsmonat_typen). Two parallel runs creating the same correspondent: HTTP 400 aborted the run without a flag; every abort now flags the document.

**Measurement (one installation, read-only; offline with classify.py as a module, plus a dry run as on import):**
- 27 Austrian payslips, duplicate hints with all older payslips of the employer as candidates: 12 (5 with the wrong
  month) → 9, all right. Date set by code: 5/27 → 27/27 (month start, "Periode 13/14" included).
- Pairwise duplicates over the stock of the account with the Austrian payslips (790 documents): 68 → 40, the 28 dropped
  are all different months, no new pair; partial copies 34 → 32 (two payslips of August/September no longer "inside" a
  compilation of January–July). Second account (853 documents, German payslips): 1 → 0 (two different social insurance
  notices of January 2019 and 2020), partial copies 1 → 1, recognised billing months 168 → 168 unchanged.
- Dry run against a target list (24 documents, `eval.py --wie-import`): type 21 → 24 (with new type descriptions in
  that installation's config), date 4 → 22, correspondent 24 → 24.
