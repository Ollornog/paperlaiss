---
type: Task
title: 'Allerweltsnamen, Marke im Trace, Stammdaten-Knopf und Eingang mit Archiv'
status: erledigt
id: T-15
milestone: M-1
tags: [korrespondent, stammdaten, eingang, marker]
created: '2026-11-14'
---
# T-15 — Allerweltsnamen, Marke im Trace, Stammdaten-Knopf und Eingang mit Archiv

**Anlass (2026-11-14):** Aus der vierten Durchsicht einer Installation und vier Wünschen ihres Betreibers.
1. Bei Seiten ohne Briefkopf legte die KI Korrespondenten aus Rollen und Kürzeln an: „Arbeitgeber“, „PA“
   (Personalabteilung), „Arbeitgeber (unbekannt)“, „Vermieter (VE 38 …)“, und erfand Klammerzusätze („AVG (Albatros
   Versicherungsdienst GmbH)“ statt des vorhandenen „AVG“).
2. Stammdaten entstehen nur nebenbei beim Import; für den Bestand fehlte ein Weg (rund zwei Drittel der
   Korrespondenten waren leer).
3. Der Marker-Tag „KI-Klassifiziert“ hing an fast jedem Dokument und störte in Listen und Filtern.
4. Paperless-Workflows können nicht nach Besitzer filtern; die eigenen Uploads eines Kontos bekamen den Personen-Tag
   nicht.
5. Der Eingangsordner löschte jede importierte Datei; gewünscht war ein Archiv mit Datum im Namen.

**Umsetzung:**
1. `allerweltsname_grund`: kein NEUER Korrespondent aus einer Rolle oder Funktion (eingebaute Liste plus
   `allerweltsnamen`), einem Platzhalter oder weniger als `korrespondent_min_zeichen` Zeichen (außer mit Rechtsform
   oder Ziffer, „bc GmbH“, „O2“); dann kein Korrespondent und ein Prüfhinweis `allerweltsname`. `klammer_erfunden`:
   ein Klammerzusatz, der nicht im Text steht, fällt vor dem Abgleich weg.
2. `CLASSIFY_STAMMDATEN=<id>`: liest die Dokumente des Korrespondenten (die der Nutzer sehen darf), fragt die KI einmal
   und prüft jeden Wert mit den Regeln von `stammdaten_nachtragen` gegen den Text seines Dokuments; eigene Kennungen
   aller Konten nie. Knopf im Korrespondenten-Dialog, Übernahme per Haken, gespeichert erst mit „Save“. Browser-Test.
3. `marker_tag` leer: die Marke steht im Trace (`klassifiziert`), ein späterer abgebrochener Lauf behält sie. Ein
   Mail-Import wartet über das leere Mail-Kontext-Feld statt über den Marker-Tag (`wartet_auf_mail`).
4. `konten.<user>.tags`: Tags, die jedes Dokument des Kontos bekommt. `eingang.py`: `tags` je Konto.
5. `eingang.py` mit `eingang`/`archiv`: nach dem Konsum (Erfolg oder Dublette) nach `Archiv/<JJJJ.MM.TT> <Name>`,
   Datum in `zeitzone`, Zähler bei Kollision; Fehlschlag bleibt mit `<name>.fehler.txt` liegen.
6. `CLASSIFY_WIE_IMPORT` / `eval.py --wie-import`: messen, als käme das Dokument gerade an.

**Messung:** Namensregel über die 268 Korrespondenten der Installation: kein vorhandener Name wäre gesperrt, alle vier
gelöschten Kunstnamen schon. Lohnabrechnungen mit Krankenkasse im Text (Anlass eines alten Befunds, BARMER statt
Arbeitgeber) mit 0.9.0 wie beim Import: 11 von 11 Läufen beim Arbeitgeber. 25 Mutanten rot, `check.sh` zweimal grün.
