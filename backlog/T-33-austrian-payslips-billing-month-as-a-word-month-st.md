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
