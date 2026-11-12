---
type: Task
title: 'Kaputte Scans, Überlast, Alias-Treffer und ein Kontrolllauf'
status: erledigt
id: T-10
milestone: M-1
tags: [ki, ocr, eval, nacharbeit, stammdaten]
created: '2026-11-12'
---
# T-10 — Kaputte Scans, Überlast, Alias-Treffer und ein Kontrolllauf

**Anlass (2026-11-12):** Ein Stapelscan von gut 400 Altdokumenten (rund 1.100 Seiten) wurde von Hand
durchgesehen. Was dabei von Auge auffiel, sollte der Code selbst finden oder gar nicht erst falsch machen.

**Befunde und Umsetzung:**
1. **Erfundener OCR-Text.** Drei leere Seiten bekamen 50× dieselbe Formelzeile als Inhalt, eine
   Lohnabrechnung ein sinnloses Gedicht; der erfundene Text ersetzte den Text, den Paperless gelesen
   hatte. Jetzt: Wiederholungsschleifen gelten als erfunden (`wiederholung`), solche Seiten fehlen im
   OCR-Text, ein erfundener Text ersetzt nie den Inhalt. Wo Ghostscript da ist, prüft der Lauf ein
   Dokument ohne Text vorher auf leere Seiten und schickt es dann gar nicht zur OCR.
2. **Überlast.** Mistral antwortete zwei Minuten lang 503; die Pausen (110 s) reichten nicht, zwei
   Dokumente blieben still unklassifiziert. Jetzt: längere Pausen, Wiederholung auch bei Paperless
   (lesend immer, schreibend nur, wenn die Antwort sagt, dass nichts ankam), und ein abgebrochener Lauf
   bekommt den Unsicher-Tag und eine Notiz.
3. **Alias nicht genutzt.** Die KI nannte den Kurznamen einer Personalfirma, die Vorsuche hatte den
   Korrespondenten über genau diesen Alias gefunden, der Lauf legte trotzdem einen neuen Korrespondenten an. Jetzt zählt ein
   eindeutiger Alias wie ein exakter Name.
4. **Falsches Gegenüber.** Krankenkasse statt Arbeitgeber auf Lohnabrechnungen (21×), Frankiervermerk
   „Deutsche Post“ als Absender (4×), Personalnummer aus einem Tabellenkopf als Kundennummer gelernt,
   eigene Person als Korrespondent (Ursache: der Scan gehörte beim Import noch dem Upload-Konto). Jetzt:
   Rückfrage nach dem Aussteller (`arbeitgeber_typen`, `einzugsstellen_muster`, eigene Person),
   Frankiervermerk neutralisiert, Personalnummer auch in der Zeile unter dem Tabellenkopf erkannt,
   `technische_konten`.
5. **Kontrolllauf.** `CLASSIFY_KONTROLLE=<ids>` prüft vorhandene Dokumente ohne KI (leer, erfundener
   Text, fehlende Seiten auch per „Fortsetzung nächste Seite“, Dublette, eigene Person, Krankenkasse)
   und markiert sie (`kaputt_tag`/`unsicher_tag`, Notiz mit Grund über `pruef_notiz`).

**Messung:** Sollliste aus den Korrekturen des Tages (125 Dokumente) — liegt neben der Config der
Installation, nicht im Repo (echte Dokumente). Ergebnis im CHANGELOG zu 0.5.0.

**Offen:** Dubletten im Kontrolllauf vergleichen nur mit den fünf ähnlichsten Dokumenten der
Paperless-Suche; Dokumente im Papierkorb sieht er nicht.
