---
type: Task
title: 'Begradigen je Dokument abschalten oder Winkel setzen, vier Ecken entzerren'
status: offen
id: T-24
milestone: M-1
tags: [ocr, panel, scan]
created: '2026-11-19'
---
# T-24 — Begradigen je Dokument abschalten oder Winkel setzen, vier Ecken entzerren

**Herkunft:** Rest aus T-8, abgespalten nach [ADR-4](ADR-4-ausrichtung-ueber-paperless-fassungen.md). Drehen in
90°-Schritten (je Seite) und kopfüber beim Import sind erledigt; offen ist alles, was ein Bild selbst verändert.

**Wunsch (PO 2026-11-11):**
- Begradigen (`OCR_DESKEW`) für ein Dokument abschalten oder den Winkel von Hand setzen.
- Im Panel vier Punkte auf die Dokumentecken ziehen, daraus perspektivisch entzerren und zuschneiden.
- Danach neu verarbeiten und neu klassifizieren; das Original bleibt erhalten.

**Was dazu fehlt:** Paperless hat keine OCR-Einstellung je Dokument und kann weder zuschneiden noch entzerren. Der Weg
wäre eine **neue Fassung** mit dem bearbeiteten Bild (`POST /api/documents/<id>/update_version/`), die Paperless wie
jede Fassung liest und paperlaiss danach neu klassifiziert (seit T-8). Bei einem schon begradigten Bild findet das
globale Begradigen keinen Winkel mehr — damit ist „Begradigen aus“ für dieses Dokument faktisch erreicht.

**Zu entscheiden (PO):**
- **Wo die Bildbearbeitung läuft:** im Paperless-Abbild (PIL, numpy und scipy sind dort schon, so arbeitet auch ein
  Zuschnitt-Vorab-Skript einer Installation) als Auftrag, den das Panel anstößt — oder im Panel-Abbild mit einer neuen
  Abhängigkeit (Pillow, Lizenz MIT-CMU). Empfehlung: Panel-Abbild mit Pillow, weil der Auftrag vom Panel kommt und das
  Paperless-Abbild nicht erweitert werden soll; PDF zu Raster dort über pypdf-Bilder bzw. Ghostscript prüfen.
- **Oberfläche:** Ecken-Ziehen braucht eine Bildansicht mit Ziehpunkten — C22 hat dafür keinen Baustein (C22-Wunsch).
- **Verlust:** ein entzerrtes Bild ist neu gerechnet (nicht verlustfrei wie `/Rotate`); das Original bleibt als
  Fassung 0.
