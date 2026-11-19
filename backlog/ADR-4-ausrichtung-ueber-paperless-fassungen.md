---
id: ADR-4
type: Decision
title: Ausrichtung beim Import per Vorab-Schritt, von Hand über die Fassungen von Paperless
status: erledigt
tags: [ocr, scan, architektur]
created: 2026-11-19
---

# ADR-4 — Ausrichtung beim Import per Vorab-Schritt, von Hand über die Fassungen von Paperless

## Problem

Beim Stapelscannen liegt ein Teil der Blätter kopfüber, manche leicht schief (T-8). Die Lageerkennung von Paperless
(Tesseract-OSD vor OCRmyPDF) trifft 90° verlässlich, 180° nicht: in einem Stapel von 117 Dokumenten lagen 25 kopfüber
und blieben so, während OSD alle Steuerbescheide mit geringer Sicherheit „180°“ nannte. Gewünscht war außerdem, je
Dokument von Hand zu drehen, das Begradigen abzuschalten oder einen Winkel zu setzen, vier Ecken zu setzen, danach neu
zu verarbeiten und neu zu klassifizieren — und das Original zu behalten.

## Was Paperless 3.4 selbst kann (Quellcode v3.4.2, `documents/bulk_edit.py`, `consumer.py`)

- **Drehen** (`bulk_edit` `rotate`, 90/180/270, ganzes Dokument) und der **PDF-Editor** (`edit_pdf`, je Seite drehen,
  Seiten entfernen, umstellen; mit „Neue Fassung“ `update_document`) legen eine **neue Fassung** an: Datei
  `<id>_rotated.pdf` bzw. `<id>_edited.pdf`, `root_document` = das Dokument, das Original bleibt als Fassung 0. Die
  neue Fassung wird wie ein Import verarbeitet (OCR), die API liefert danach ihren Text am Dokument.
- **Neu verarbeiten** (`reprocess`) liest die neueste Fassung neu, mit den **globalen** OCR-Einstellungen.
- **Je Dokument** gibt es keine OCR-Einstellung: Begradigen (`OCR_DESKEW`), Drehen (`OCR_ROTATE_PAGES`) und Schwelle
  gelten für alle. Zuschneiden oder perspektivisch entzerren kann Paperless nicht.
- Der Post-Consume-Lauf einer neuen Fassung bekommt die ID der Fassung; die API zeigt Fassungen nicht
  (`/documents/<fassung>/` → 404). Bis 0.13 endete deshalb jedes Drehen als FEHLER im Log, und das Dokument behielt
  die Klassifizierung seines kopfüber gelesenen Texts.

## Entscheidung

1. **Kopfüber beim Import** erkennt ein neuer Vorab-Schritt `deploy/vorab/ausrichtung.py` (Schalter
   `kopfueber_drehen`, Vorgabe an): jede gescannte Seite einmal wie sie ist und einmal um 180° gedreht mit Tesseract
   lesen, drehen nur bei klar besserer Lesung. Geändert wird nur `/Rotate` der Seite (qpdf), das Bild bleibt
   byte-gleich — verlustfrei, deterministisch (Dubletten per Prüfsumme bleiben erkennbar) und mit dem Drehen in
   Paperless rückgängig zu machen. Vor dem Import gibt es noch kein Dokument und keine Fassung; der Eingriff hat
   dieselbe Art wie das Entfernen leerer Seiten. 90° bleibt bei Paperless.
2. **Von Hand drehen** (ganzes Dokument oder je Seite) bleibt in Paperless: Drehen bzw. PDF-Editor mit „Neue
   Fassung“. Kein eigener Dreh-Dialog im Panel — fertiger Dienst vor Eigenbau, und die Fassung bewahrt das Original.
   Die Wahl steckt in der Datei der Fassung; ein späteres „Neu verarbeiten“ liest diese Datei und kippt sie nicht.
3. **Neu klassifizieren nach einer neuen Fassung** übernimmt `classify.py`: liefert die API für die ID des
   Post-Consume-Laufs 404, sucht es das Dokument über den Dateinamen (`<id>_rotated.pdf`, `<id>_edited.pdf`) und
   bestätigt es über dessen `versions`-Liste. Dann läuft es wie der KI-Knopf (Typ und Titel dürfen ersetzt werden;
   was der vorige Lauf auf dem kopfüber gelesenen Text gesetzt hat, räumt das Aufräumen aus T-9 Punkt 5 weg, soweit
   seither niemand die Klassifizierung von Hand geändert hat). Eine
   Fassung mit fremdem Dateinamen (eigene Datei hochgeladen) wird nur übersprungen und protokolliert — dort hilft der
   KI-Knopf.
4. **Begradigen je Dokument abschalten oder Winkel setzen, vier Ecken setzen** wird jetzt **nicht** gebaut: dafür
   müsste paperlaiss selbst Bilder bearbeiten (Raster drehen um einen beliebigen Winkel, perspektivisch entzerren) und
   das Ergebnis als neue Fassung hochladen. Das Panel-Abbild hat dafür keine Bildbibliothek; im Paperless-Abbild gäbe
   es PIL, numpy und scipy. Das ist eine neue Abhängigkeit bzw. ein neuer Ausführungsort und eine eigene
   Entscheidung → Task T-24.

## Folgen

- Ein Release hat acht Anhänge (neu `ausrichtung.py`); eine Installation, die die Vorab-Schritte einzeln einträgt,
  muss die Datei mit ausliefern. Fehlt sie, überspringt `vorab.py` den Schritt.
- Rechenzeit beim Import: gemessen rund eine Sekunde je gescannter Seite (zweite Lesung nur bei schwacher erster),
  höchstens 60 Seiten und vier Minuten je Dokument.
