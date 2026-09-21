---
id: T-1
type: Task
title: Vier Panel-Blöcke aus der Flask-Fassung übernehmen
status: erledigt
milestone: M-1
tags: [panel, ui]
created: 2026-09-21
---

# T-1 — Vier Panel-Blöcke aus der Flask-Fassung übernehmen

Es gibt eine ältere, produktiv gewachsene Panel-Fassung (Flask, rund 1300 Zeilen) neben der
schlanken FastAPI-Fassung dieses Repos. Vier ihrer Blöcke sind allgemein nützlich und fehlen
hier wirklich — der Rest ist installationsspezifisch und bleibt draußen.

**Zu übernehmen:**

1. **Einstellungs-Formular** — alle Konfigurationswerte in der Oberfläche änderbar, statt die
   JSON-Datei von Hand zu bearbeiten. Schlüsselfelder bleiben ausgespart (sie gehören in die
   Umgebung, siehe `GEHEIM_FELDER`).
2. **Korrespondenten zusammenführen** — zwei Einträge verschmelzen und die Dokumente umhängen.
   Ohne das sammeln sich Dubletten, die der Feedback-Loop zwar vermeidet, aber nicht aufräumt.
3. **Auswertung über 30 Tage** — Verlauf klassifiziert/OCR plus eine Liste der Auffälligkeiten
   mit Erkennung, was inzwischen gelöst ist.
4. **Trace-Ansicht als HTML** — heute liefert `/api/trace/{id}` nur JSON. Die schrittweise
   Darstellung ist genau das, was man beim Nachvollziehen eines Laufs braucht.

**Nicht übernehmen:** Vertrags-/Bestandstabellen und die Bulk-Steuerung — beides hängt an
Fremdsystemen einer einzelnen Installation. Dafür gibt es seit 2026-09-21 die Naht
`nachbearbeitung` (→ ADR-3).

**Fertig, wenn** die vier Blöcke in der FastAPI-Fassung laufen, die Authentifizierung über
`guard()` greift und die reine Logik in `panel/kern.py` getestet ist.


## Erledigt 2026-09-21

Alle vier Blöcke gebaut, die reine Logik in `panel/kern.py` getestet (Merge, Typumwandlung,
Verlauf, Auffälligkeiten). Am Testbett gegen echte Daten geprüft, inklusive des typsicheren
Speicherpfads: `"350"` → `350`, `"0,2"` → `0.2`, `"dreihundert"` → übergangen und gemeldet.

Nicht übernommen wie geplant: Vertrags-/Bestandstabellen und Bulk-Steuerung — dafür gibt es
die Naht `nachbearbeitung` (ADR-3).
