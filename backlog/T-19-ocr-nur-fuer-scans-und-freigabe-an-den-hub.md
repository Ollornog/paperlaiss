---
type: Task
title: 'OCR nur für Scans und Fotos, Freigabe an den Hub ohne Tag'
status: erledigt
id: T-19
milestone: M-1
tags: [ocr, kosten, routing, rechte]
created: '2026-11-15'
---
# T-19 — OCR nur für Scans und Fotos, Freigabe an den Hub ohne Tag

**Anlass (2026-11-15):** Zwei Installationen lesen seit `ocr_always: true` jedes neue Dokument per Mistral-OCR, auch
digitale PDFs, deren Text Paperless schon fehlerfrei hat. Frage des Betreibers: lässt sich zwischen digitalen PDFs und
gescannten unterscheiden?

**Umsetzung OCR:** neuer Schlüssel `ocr_modus` (`rescue`, `scans`, `immer`; `ocr_always` bleibt Kurzform für `immer`).
Im Modus `scans` misst `classify.py` jede Seite des Originals: Anteil der Seite unter Rasterbildern (Raster 40 × 40,
Vereinigung statt Summe) und Bytes sichtbaren und unsichtbaren Texts (Render-Modus 3 und 7 unsichtbar), samt
Form-XObjects und Inline-Bildern. Scan-Seite: Bildanteil ≥ 0,6 und sichtbar < 400 Byte. Ein Scan-Blatt genügt
(gemischtes Dokument), Fotos immer, andere Formate nie. Nicht prüfbar → OCR. Bibliothek: pikepdf im Paperless-Abbild,
pypdf im Panel-Abbild, beide optional.

**Messung (vor dem Bau, nur lesend, je Seite am Original):** Installation A 1.645 Dokumente / 4.562 Seiten: 551
digital (1.613 Seiten, 35 %), 992 Scans, 36 gemischt, 66 Fotos. Installation B 1.095 / 1.367: 623 digital (811 Seiten,
59 %), 467 Scans, 1 gemischt, 4 Fotos. Grenzwerte aus derselben Messung: Scanner-Seiten 100 % Bild und 0 Byte sichtbar;
in Word eingefügte Zeugnis-Scans 64–78 % Bild mit 250–310 Byte Kopfzeile (zählen als Scan); digitale Seiten mit
ganzseitigem Hintergrund (Briefpapier, Formular-Overlay, Acrobat Sign) 680–3.700 Byte (digital). Kurze Urkunden auf
Hintergrund (155–330 Byte) zählen als Scan: eine Seite OCR zu viel kostet weniger als ein schlecht gelesener Scan.

**Umsetzung Routing:** `PANEL_ROUTE_SHARE_WITH_HUB` (Konten, deren eigene Dokumente dem Hub immer Sehen und Ändern
geben). Anlass: eine Person lädt über die Weboberfläche hoch, ohne ihr Tag zu setzen; der Hub sah das Dokument nicht.

**Tests:** Fachtests mit synthetischen Inhaltsströmen und am Lauf (`main()`); Abbild-Test `tests/abbild_ocr_art.py`
an echten Originalen aus Ghostscript, img2pdf, OCRmyPDF/Tesseract und qpdf (`tests/fixtures/ocr-art/erzeugen.sh`) im
Paperless-Abbild (pikepdf) und im Panel-Abbild (pypdf), beide Bibliotheken messen gleich.
