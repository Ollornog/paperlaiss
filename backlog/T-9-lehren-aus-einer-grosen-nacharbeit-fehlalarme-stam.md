---
type: Task
title: 'Lehren aus einer großen Nacharbeit: Fehlalarme, Stammdaten, Korrespondent'
status: in-arbeit
id: T-9
milestone: M-1
tags: [ki, eval, stammdaten, nacharbeit]
created: '2026-11-11'
---
# T-9 — Lehren aus einer großen Nacharbeit: Fehlalarme, Stammdaten, Korrespondent

**Anlass (PO 2026-11-11):** Ein Stapel von gut hundert gescannten Altdokumenten (Lohn, Sozialversicherung, Steuer) und rund hundert ältere Dokumente mit „KI-unsicher“ wurden von Hand gegengelesen. Ergebnis: Korrespondent bei 32 von 110 falsch, Typ bei 27, Datum bei 12, viele Fehl-Tags; **alle 101 „KI-unsicher“-Markierungen waren Fehlalarme**.

**Ursachen und Vorschläge (Code):**
1. **Eigene Kennungen wurden als Stammdaten gelernt.** Die eigene IBAN eines Kontos stand nicht in `eigene_kennungen` und landete bei einer Krankenkasse, dazu Personalnummern zweier Arbeitgeber als „Kundennummer“. Danach meldete jede Lohnabrechnung „gehört schon zu …“. Vorschlag: Eine Kennung, die auf Dokumenten vieler verschiedener Korrespondenten vorkommt, nicht lernen, sondern als „wahrscheinlich eigene“ im Panel vorschlagen. Nummern mit Beschriftung „Personal-Nr.“ nie als Kundennummer übernehmen.
2. **Sammeldokument-Regel trifft Kontoauszüge.** Auf Kontoauszügen stehen naturgemäß Kennungen vieler Gegenüber. Regel für Kontoauszug/Kreditkartenabrechnung aussetzen.
3. **Dubletten-Regel trifft Serienbriefe** (gleicher Text an verschiedene Empfänger). Zusätzlich Zahlen/Daten/Anrede vergleichen; umgekehrt echte Doppelscans (gleicher Text, gleiche Zahlen) melden — die fand heute keiner.
4. **Korrespondent = eigene Person.** Bei Formularen nahm die KI den Empfänger (eigener Name) oder die Einzugsstelle statt des Arbeitgebers. Nachprüfung im Code: Ist der Korrespondent einer der eigenen Namen und der Typ nicht selbst verfasst, zweiter Versuch bzw. „KI-unsicher“ mit Grund.
5. **Neu klassifizieren räumt nicht auf.** Ein erzwungener Lauf fügt nur hinzu: Tags und Felder eines früheren Fehllaufs (z. B. auf kopfüber gelesenem Text) bleiben stehen. Was der vorige Lauf laut Trace gesetzt hat und kein Mensch bestätigt hat, vor dem neuen Lauf entfernen.
6. **Kein Datum im Text** → nicht still das Importdatum lassen, sondern „KI-unsicher“ mit Grund oder ein geschätztes Datum mit Notiz.
7. **Grund von „KI-unsicher“ sichtbar machen** (Notiz am Dokument oder Spalte im Panel), damit man nicht jedes Dokument öffnen muss.
8. **Nacharbeit misst zu wenig:** zählt nur Änderungen angemeldeter Benutzer, wird nur auf Knopfdruck aufgefrischt. Regelmäßig auffrischen; Korrekturen aus einem Gegenlese-Lauf als Sollliste für `eval.py` übernehmen.
9. **Modell gepinnt statt `*-latest`**, Formulare probeweise mit einem größeren Modell gegen die Sollliste messen.

**Stand:** Punkte 1–6 als Fehlerbehebung umgesetzt (CHANGELOG „Unreleased“, Abschnitt „Behoben“). Offen aus 1: die wahrscheinlich eigene Kennung im Panel vorschlagen (heute wird sie nur nicht gelernt und nicht gemeldet) und früher falsch gelernte Werte aus dem Store räumen. Offen: 7–9.

**Vorschläge (Konfiguration/Prompt, je Installation):**
- Typbeschreibungen für Lohnsteuerbescheinigung, Lohn-/Gehaltsabrechnung, Meldebescheinigung zur Sozialversicherung, Meldebestätigung (Wohnsitz) — heute fehlen sie, die Typen werden verwechselt.
- Tag-Beschreibungen mit Gegenbeispielen („Meldewesen: NICHT Meldebescheinigung zur Sozialversicherung“, „Gesundheit: nicht nur weil eine Krankenkasse absendet“, „Steuer: nicht Sozialversicherungsmeldungen“).
- Prompt-Hinweis: Bei Formularen mit Feldern „Name und Anschrift des Arbeitgebers“ / „Einzugsstelle“ / „Finanzamt, an das die Lohnsteuer abgeführt wurde“ ist der Korrespondent der Arbeitgeber.
- Titel-Vorlagen je Typ (z. B. „Einkommensteuerbescheid <Jahr>“), damit Serien einheitlich heißen.
