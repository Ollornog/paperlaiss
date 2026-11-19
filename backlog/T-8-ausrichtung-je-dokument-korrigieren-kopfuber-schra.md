---
type: Task
title: 'Ausrichtung je Dokument korrigieren: kopfüber, Schräglage, Ecken'
status: erledigt
id: T-8
milestone: M-1
tags: [ocr, panel, scan]
created: '2026-11-11'
---
# T-8 — Ausrichtung je Dokument korrigieren: kopfüber, Schräglage, Ecken

**Anlass (PO 2026-11-11):** Beim Stapelscannen liegt ein Teil der Dokumente kopfüber im Archiv, manche werden leicht schief gedreht. Die automatische Ausrichtung (Drehen und Begradigen beim OCR) trifft meistens sehr gut, aber nicht immer. Sie soll an bleiben, aber je Dokument überschreibbar sein.

**Idee:**
- **Kopfüber erkennen:** Seiten, die auf dem Kopf stehen (180°), zuverlässig erkennen und drehen, auch wenn die OCR-Drehung nicht greift (z. B. Vergleich der OCR-Güte normal gegen gedreht).
- **Je Dokument überschreiben:** Im Panel je Seite drehen (90/180/270) und das Begradigen für dieses Dokument abschalten oder den Winkel von Hand setzen, danach neu verarbeiten. Die Wahl bleibt am Dokument gespeichert, damit ein späteres „erneut verarbeiten“ sie nicht wieder kippt.
- **Vier Ecken setzen:** Im Panel vier Punkte auf die Dokumentecken ziehen; daraus perspektivisch entzerren und zuschneiden (wie Handy-Scan-Apps), dann neu verarbeiten.
- Danach automatisch neu klassifizieren, weil sich der OCR-Text ändert.

**Offen:**
- Was kann Paperless selbst (Seiten drehen per `bulk_edit` `rotate`, Neuverarbeitung mit globalen OCR-Einstellungen), und was braucht eigene Bildbearbeitung?
- Wird das Original ersetzt oder eine bearbeitete Fassung abgelegt? Das Original sollte erhalten bleiben.

**Stand 2026-11-19 (Entscheidungen: [ADR-4](ADR-4-ausrichtung-ueber-paperless-fassungen.md)):**
- Kopfüber beim Import: neuer Vorab-Schritt `ausrichtung.py` (Schalter `kopfueber_drehen`) — Tesseract liest jede
  gescannte Seite wie sie ist und um 180° gedreht, gedreht wird nur bei klar besserer Lesung; nur `/Rotate`, das Bild
  bleibt.
- Je Seite drehen: in Paperless selbst (Drehen, PDF-Editor mit „Neue Fassung“); das Original bleibt als Fassung 0.
- Danach neu klassifizieren: `classify.py` erkennt den Post-Consume-Lauf einer neuen Fassung und klassifiziert das
  Dokument neu (bis 0.13 FEHLER im Log).
- Begradigen je Dokument / Winkel / vier Ecken: abgespalten nach T-24 (braucht eigene Bildbearbeitung).
