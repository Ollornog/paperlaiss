---
type: Task
title: 'Titel-Bruchstück und spiegelbildliche Dokumente als Dublette'
status: erledigt
id: T-17
milestone: M-1
tags: [titel, dubletten]
created: '2026-11-14'
---
# T-17 — Titel-Bruchstück und spiegelbildliche Dokumente als Dublette

**Anlass (2026-11-14):** Zwei Scans einer „General- und Vorsorgevollmacht“, spiegelbildlich (Vollmachtgeber und
Bevollmächtigter vertauscht). Beide bekamen den Titel „Name – Vollmacht General- und“, und der zweite wurde als Dublette
des ersten gemeldet.

**Ursachen:**
1. `titel_bilden` entfernt Wörter der Kennung, die auf die Dokumentart enden („Ersatzteilrechnung“ bei Rechnung). Aus
   „General- und Vorsorgevollmacht“ fiel „Vorsorgevollmacht“ weg, übrig blieb „General- und“.
2. `dublette` vergleicht Zahlen als Menge. Zwei spiegelbildliche Formulare tragen dieselben Geburtsdaten, Postleitzahlen
   und dasselbe Datum, nur in anderer Reihenfolge. Gemeldet hatte es noch 0.6. Die Mindestzahl aus T-12 (0.7, fünf
   Zahlen je Seite) fängt den Anlassfall nur, weil die OCR beim ersten Scan drei Zahlen las; mit fünf Zahlen auf beiden
   Seiten waren die Mengen gleich und die Meldung käme wieder.

**Umsetzung:**
1. `_haengt_an`: steht ein Bindewort (und, oder, sowie, bzw., &, +, /) vor oder nach dem Wort, oder trägt es einen
   Schrägstrich, bleibt die Kennung ganz und ersetzt die Dokumentart im Titel.
2. `gleiche_reihenfolge`: die gemeinsamen Datumsangaben (keine Beträge, keine anderen Zahlen) stehen in beiden
   Texten in derselben Reihenfolge, sonst keine Dublette.

**Messung:** 10 Mutanten rot, `check.sh` zweimal grün. Bestand einer Installation (trocken, nichts geschrieben):
Titel neu gerechnet aus 1.131 Traces mit Kennung, 7 ändern sich, alle mit Bruchstück („… General- und“, „Rechnung Heiz-
und 2020“); Dubletten über alle Paare von 1.366 Dokumenten mit mindestens fünf Zahlen: 68 Treffer vorher, alle 68
bleiben (die neue Bedingung kann keinen Treffer hinzufügen).
