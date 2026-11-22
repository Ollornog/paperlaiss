---
type: Task
title: Detect duplicates between a digital original and a scan
status: offen
id: T-25
milestone: M-1
created: '2026-11-22'
---
# T-25 — Detect duplicates between a digital original and a scan

Paperless detects duplicates only by file checksum, so the same invoice as an original PDF and as a scan are two files and never show up. To work out with the owner. Approaches: match key fields (correspondent, invoice number, amount, date), text similarity after OCR, Paperless' own similar documents. Open: what happens on a hit (tag 'duplicate?', merge, delete the scan copy). Migrated from the old central backlog page (status 2026-10-14).
