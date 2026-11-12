---
type: Task
title: 'Feldfilter, Tag-Ausschluss, Dubletten und Stammdaten aus einer zweiten Durchsicht'
status: erledigt
id: T-11
milestone: M-1
tags: [ki, felder, tags, dubletten, stammdaten, kontrolllauf, eval]
created: '2026-11-12'
---
# T-11 — Feldfilter, Tag-Ausschluss, Dubletten und Stammdaten aus einer zweiten Durchsicht

**Anlass (2026-11-12):** Eine zweite Durchsicht aller gut 700 Dokumente einer Person (einer Installation)
nach den Fehlerquellen aus T-9 und T-10. Was von Hand korrigiert werden musste, soll der Code nicht mehr
falsch machen.

**Befunde und Umsetzung:**
1. **IBAN-Felder.** 53 Feldwerte waren keine IBAN: aus Bankleitzahl und Kontonummer alter Lohnabrechnungen
   zusammengesetzt, mit falscher Prüfziffer. Jetzt: nur mit gültiger Prüfziffer (ISO 13616, mod 97) und
   Länderlänge, und nur, wenn sie so im Text steht — im Feld und in den Stammdaten.
2. **Personal- und Abrechnungsnummern als Vertrags-/Rechnungsnummer oder Aktenzeichen** (37
   Lohnabrechnungen). Die Nummer im Kopf („611 7437/ 40/88901“) enthält die Personalnummer, die weiter
   unten neben „Pers.-Nr.“ steht. Jetzt: ein Kennungsfeld nimmt keine Personalnummer und keinen Wert, der
   eine als Teil enthält; bei den Typen aus `arbeitgeber_typen` füllt die KI die Felder aus
   `arbeitgeber_ohne_felder` (Vorgabe Vertragsnummer, Rechnungsnummer, Aktenzeichen) nie.
3. **Tags, die sich ausschließen.** Lebens- und Rentenversicherungen bekamen „Versicherungen“ neben
   „Vorsorge“; eine schärfere Tag-Beschreibung half nicht (gemessen). Jetzt: `tag_ausschluss`, eine Regel
   je Tag mit Ausnahmen per Muster im Text (etwa Berufsunfähigkeit oder Unfall).
4. **Dubletten und Teilkopien.** Der Scan eines digitalen Originals blieb unentdeckt (die OCR verlor zwei
   Zahlen, die Mengen waren nicht gleich), Teilkopien (Seiten 1–2 eines vierseitigen Schreibens) fand nur
   das Auge. Jetzt: Dublette, wenn die Zahlen des einen die des anderen bis auf wenige enthalten;
   Teilkopie, wenn ein Dokument mit weniger Seiten alle seine Zahlen (mindestens 8) mit einem längeren
   teilt; Kandidaten zusätzlich per Inhaltssuche nach den zwei größten Beträgen.
5. **Stammdaten.** Eigene Nummern wanderten in fremde Einträge: die Personalnummer beim Finanzamt (Ursache
   falscher Korrespondenten), die eigene Kontonummer als Kundennummer bei vier Gegenübern, zehn Nummern am
   Eintrag der eigenen Person. Jetzt: nicht gelernt wird, was am Eintrag einer eigenen Person steht (alle
   eigenen Namen, nicht nur der Besitzer), und keine Kundennummer, die schon bei einem anderen
   gespeichert ist; der Eintrag einer eigenen Person bekommt keine Kennungen. Kein Prüfhinweis dafür.
6. **Kontrolllauf-Fehlalarme.** Ein Seitenkopf auf jeder von 13 Seiten galt als erfundener Text, eine
   überlange Seite (zwei Seiten in einem Bild, OCR „Seite 2 van 2“) als Teilstück. Jetzt: eine Zeile, die
   höchstens einmal je Seite vorkommt, ist ein Kopf; die Wortschleife ohne Zeilen greift nur ohne
   Zeilenstruktur oder bei sehr kleinem Wortschatz; „van“/„v0n“ gelten als „von“; sind alle Seiten 1 … y
   genannt, fehlt nichts.

**Messung:** Sollliste der Installation (123 Dokumente, nicht im Repo) mit 0.5.0 und 0.6.0, je zwei
Trockenläufe; Kontrolllauf über alle Dokumente der Person vorher und nachher. Ergebnis im CHANGELOG zu
0.6.0. `eval.py` hält dafür je Lauf Felder, Tags, Befunde und Stammdaten fest (`roh`).

**Offen:** Teilkopien werden über die Zahlen erkannt, nicht Seite für Seite (der Text aus Paperless hat
keine Seitengrenzen). Versandcodes aus Barcodes („*ZZ1*…*“) werden noch als Kundennummer gelernt.
