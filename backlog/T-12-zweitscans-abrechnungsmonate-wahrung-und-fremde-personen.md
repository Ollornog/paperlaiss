---
type: Task
title: 'Zweitscans, Abrechnungsmonate, Währung und fremde Personen aus einer dritten Durchsicht'
status: erledigt
id: T-12
milestone: M-1
tags: [ki, dubletten, datum, felder, stammdaten, routing, kontrolllauf]
created: '2026-11-13'
---
# T-12 — Zweitscans, Abrechnungsmonate, Währung und fremde Personen aus einer dritten Durchsicht

**Anlass (2026-11-13):** Ein dritter Stapelscan einer Person (rund 140 Dokumente, viele alte Lohnabrechnungen und
Steuerbescheide) wurde von Hand gegen den Bestand abgeglichen. Die Person hatte einen Teil schon einmal gescannt und
Dokumente mit fehlender Seite noch einmal. Was von Hand korrigiert werden musste, soll der Code erkennen.

**Befunde und Umsetzung:**
1. **Zweitscans.** Elf Bescheide lagen ein zweites Mal vor; der Kontrolllauf fand vier. Zwei OCR-Lesungen desselben
   Papiers lesen je andere Zahlen falsch, die Teilmengen-Regel aus T-11 greift nicht. Jetzt (ab zwei Seiten): beide mit
   mindestens 15 Kennzahlen, 88 % der kleineren und 75 % der Vereinigung gemeinsam, keine abweichende Zahl ist ein Datum
   oder Abrechnungsmonat. Über den Bestand gemessen kein Fehlalarm; einseitige bleiben streng (T-11).
2. **Fehlalarme.** Zwei Korrekturabrechnungen (Januar, März) desselben Tags und zwei Vollmachten in Gegenrichtung
   galten als Dublette. Jetzt zählt der Abrechnungsmonat zu den Kennzahlen, und das Gegenstück braucht selbst fünf.
3. **Datum auf Lohnabrechnungen.** Sie nennen nur Monat und Jahr („8 / 99“); der Monatsletzte stand nicht im Text, das
   Datum blieb der Importtag. Jetzt belegt Monat und Jahr den ersten oder letzten Tag des Monats.
4. **Währung.** DM-Beträge wurden als EUR gespeichert, deutsche Tausenderpunkte als Dezimalpunkt gelesen. Jetzt bleibt
   die Währung des Dokuments (DM → DEM).
5. **Eigene Anschrift in den Stammdaten.** Der Empfängerblock stand als Adresse bei acht Gegenübern. Jetzt Vergleich
   nach Straße und Hausnummer; steht sie bei einer eigenen Person, wird sie nicht gelernt. Dazu: ein vom OCR zerrissenes
   Etikett „Persona Inummer“ gilt als Personalnummer-Etikett.
6. **Krankenkasse in Komposita.** „BUNDESKNAPPSCHAFT“ entging dem Muster `\bKnappschaft`.
7. **Fremde Personen.** Bescheide und Abrechnungen einer früheren Partnerin lagen im Stapel. Neuer Schlüssel
   `fremde_namen` (auch je Konto) und Prüfhinweis `fremde_person`.
8. **Upload-Konto beim Routing.** Ein Scanner verlor nach dem Hochladen das Netz und konnte den Besitzer nicht mehr
   setzen; `/route` teilte nur. Jetzt übergibt es Dokumente der Konten aus `PANEL_ROUTE_UPLOADERS` wie die der Zentrale.

**Messung:** Paare aus dem Stapel (14 Zweitscans, 16 ähnliche, verschiedene Dokumente): erkannt 6 → 12, Fehlalarme
3 → 0. Über rund 1.400 Dokumente der Installation alle Dokumentpaare gleicher Seitenzahl, alte gegen neue Fassung.

**Offen:** Teilkopien mit verlesenen Zahlen (ein Teilscan in schlechterer Qualität, ein Nachscan, dem eine Seite fehlte)
bleiben unerkannt: ohne Seitengrenzen im Text fand eine tolerante Regel drei falsche Paare. Ein einseitiger Zweitscan
mit verlesenen Zahlen ebenso (Schutz der Serienbriefe aus T-11).
