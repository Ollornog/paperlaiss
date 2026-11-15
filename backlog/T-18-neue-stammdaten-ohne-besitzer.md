---
type: Task
title: 'Neue Stammdaten ohne Besitzer, auch unter einem Dienstkonto'
status: erledigt
id: T-18
milestone: M-1
tags: [rechte, dienstkonto]
created: '2026-11-15'
---
# T-18 — Neue Stammdaten ohne Besitzer, auch unter einem Dienstkonto

**Anlass (2026-11-15):** Eine Installation stellt paperlaiss von einem Personenkonto mit Superuser-Rechten auf ein
eigenes Dienstkonto um, die Person verliert den Superuser. Paperless macht beim Anlegen eines Korrespondenten oder Tags
das aufrufende Konto zum Besitzer, solange die Anfrage keinen Besitzer nennt (`OwnedObjectSerializer.create`). Ein
Korrespondent, der dem Dienstkonto gehört, ist für jede Person ohne Superuser unsichtbar: Dokumente zeigen dann einen
leeren Korrespondenten.

**Umsetzung:** `classify.py` legt neue Korrespondenten mit `"owner": null` an, das Panel neue Quelle-Tags
(`/ingest`) ebenso. Ohne Besitzer sind sie für alle Konten sichtbar, wie der übrige Bestand.

**Messung:** Je ein Mutant (Schlüssel `owner` entfernt) rot: drei Prüfungen in `test_classify.py`, eine in
`test_panel.py`. Bestand zweier Installationen vorher gemessen: alle Tags, Korrespondenten, Dokumenttypen und
Ablagepfade ohne Besitzer.
