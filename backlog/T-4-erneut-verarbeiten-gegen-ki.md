---
id: T-4
type: Task
title: Paperless' „Erneut verarbeiten" überschreibt den OCR-Text des KI-Knopfs
status: verworfen
milestone: M-1
tags: [paperless, knoepfe, ocr]
created: 2026-09-27
---

# T-4 — „Erneut verarbeiten" gegen „KI"

Paperless' eigene Aktion **Erneut verarbeiten** (Dokumentansicht und Mehrfachauswahl) liest ein
Dokument mit der lokalen Texterkennung (Tesseract) neu und baut Thumbnail und Archiv-PDF neu
(`documents.tasks.update_document_content_maybe_archive_file`). paperlaiss läuft danach **nicht**.

Wer nach **KI** auf **Erneut verarbeiten** drückt, ersetzt den Mistral-OCR-Text durch den meist
schwächeren Tesseract-Text — ohne neue Klassifizierung.

**Möglichkeiten:** den Menüpunkt über `paperlaiss-knoepfe.js` ausblenden (wie „Suggest") — dann
fehlt aber der Neubau von Archiv-PDF und Thumbnail, falls er gebraucht wird; oder daneben einen
Hinweis zeigen; oder nach „Erneut verarbeiten" automatisch KI anstoßen.

**Fertig, wenn** entschieden ist, welcher Weg gilt, und der Knopf entsprechend umgebaut ist.
Bis dahin bewusst so gelassen (PO 2026-09-27: „lass das dann im todo für später").

## Entscheidung (2026-09-27)

Verworfen: Der PO lässt das Verhalten so. „Erneut verarbeiten" und „KI" bleiben nebeneinander
stehen; wer nach dem KI-Knopf „Erneut verarbeiten" drückt, bekommt wieder den Paperless-Text.
