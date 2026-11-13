---
type: Task
title: 'Duplex-Rückseiten, Papierscans digitaler Originale, Sammelmappen und Namensvarianten aus einer vierten Durchsicht'
status: erledigt
id: T-13
milestone: M-1
tags: [leerseiten, dubletten, stammdaten, korrespondent, kontrolllauf]
created: '2026-11-13'
---
# T-13 — Duplex-Rückseiten, Papierscans digitaler Originale, Sammelmappen und Namensvarianten

**Anlass (2026-11-13):** Ein vierter Stapel (106 Scans, nachgeladen nach einem Netzausfall des Scanners) bestand zu
zwei Dritteln aus Papierausdrucken von Lohnabrechnungen, deren digitale Originale schon im Bestand lagen. Von Hand
abgeglichen: 65 Abrechnungen Betrag für Betrag gleich, dazu fünf weitere Zweitscans, sieben Einzelbriefe aus einer
48-seitigen Sammelmappe des Arbeitgebers und zwei neu angelegte Korrespondenten, die es schon gab.

**Befunde und Umsetzung:**
1. **Gelochte Rückseiten blieben stehen.** Der Duplex-Scan liefert zu jedem gelochten Blatt eine leere Rückseite mit
   zwei runden, dunklen Flecken (gut 5 mm, rund 11 mm vom Rand); `leerseiten.py` hielt das für Inhalt (mehr als 400
   dunkle Punkte). 41 leere Seiten im Stapel, davon 0 entfernt. Folge: Ein zweiseitiges Original und sein Scan hatten
   verschiedene Seitenzahlen, die Dubletten-Prüfung verglich sie nicht (15 Paare). Jetzt zählen bis zu vier runde
   oder ovale, gefüllte Flecken von 4–9,5 mm mit der Mitte höchstens 25 mm vom Blattrand nicht als Inhalt.
2. **Einseitige Papierscans digitaler Originale.** Ein Lohnzettel hat rund 55 Kennzahlen, das OCR verliest eine oder
   zwei; die Teilmengen-Regel greift dann nicht, die OCR-Regel aus T-12 galt erst ab zwei Seiten (Schutz der
   Serienbriefe aus T-11). Jetzt gilt sie auch für eine Seite, wenn die abweichenden Zahlen nach Lesefehlern aussehen:
   Jede Zahl der einen Seite hat auf der anderen einen nahen Zwilling (höchstens zwei Ziffern anders oder
   abgeschnitten), und was die andere Seite darüber hinaus hat, bleibt in der Toleranz. Eine eigene Nummer je Brief
   (1234567/7654321) bleibt keine Kopie.
3. **Sammelmappe.** Ein Einzelbrief, der auch in einer Mappe aller Briefe des Arbeitgebers liegt, wurde nicht als
   Teilkopie erkannt: verglichen wurde nur die erste Anrede der Mappe. Jetzt zählt jede Anrede der Mappe.
4. **Kundennummer als Liste.** Das Modell gab „007/200/73702/1, 73702/1, 1160/Werkstatt ET AVG“ als eine Kundennummer;
   gespeichert wurden sechs solche Listen und zweimal die Kostenstelle. Jetzt wird eine Liste geteilt, jeder Teil geprüft,
   eine Kostenstelle („Kostenstelle“, „Kst.“) nie gelernt.
5. **Namensvarianten.** „abel Prozessdienste GmbH“ (das OCR verschluckte das T eines Alias von „Tabel GmbH“) und
   „Deutsche Bank Privat- und Geschäftskunden AG“ (Langform von „Deutsche Bank“) wurden neu angelegt. Die
   Kandidatenwahl für Pass 2 sah nur den Namen, nicht die Aliase; die Namensregel ließ „Deutsche Bank“ nicht durch
   (beide Wörter häufig). Jetzt zählt die Ähnlichkeit über Name und Aliase, und ein Vorschlag, der mit dem ganzen
   Namen des Kandidaten beginnt (ab zwei Wörtern), geht an Pass 2. Zuordnen tut weiter Pass 2.

**Messung:** Kontrolllauf auf dem Stapel 47 → 54 von 78 erkannt, mit entfernten Rückseiten 69; über rund 1.700
Dokumente kein neuer Fehlalarm. Leerseiten: 40 von 41 leeren Rückseiten, keine der 257 Seiten mit Inhalt.

**Offen:** Leere Rückseiten, die schon im Bestand liegen, bleiben (die Regel greift beim Import). Die Seitenzahl-
Gleichheit der Dubletten-Prüfung bleibt; ein Original gegen einen alten Scan mit Rückseiten fällt weiter durch. Ein
einseitiger Scan, der eine Zahl in drei Ziffern verlas („55,05“ → „39,03“), bleibt unerkannt.
