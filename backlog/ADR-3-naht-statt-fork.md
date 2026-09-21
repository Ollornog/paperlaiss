---
id: ADR-3
type: Decision
title: Installationseigene Schritte über eine Naht statt über Forks
status: erledigt
tags: [architektur, wartbarkeit]
created: 2026-09-21
---

# ADR-3 — Installationseigene Schritte über eine Naht statt über Forks

## Problem

Der Klassifizierer soll mandantenneutral bleiben, aber echte Installationen brauchen mehr als
Klassifizierung: eine Verknüpfung in ein Fremdsystem, hauseigene Regeln, eine Meldung an einen
Chat. Ohne Vorkehrung wird dafür der Code kopiert und erweitert.

Genau das ist passiert — mit dem Ergebnis, dass mehrere Stände nebeneinander liefen und ein
Fehler mehrfach behoben werden musste. Zwei davon wurden erst im September gefunden, obwohl sie
seit Juli in allen Ständen steckten.

## Entscheidung

Ein optionaler Konfigurationsschlüssel `nachbearbeitung` nennt ein Skript, das **nach** dem
Writeback läuft. Es bekommt Dokument-ID, Erfolg, den geschriebenen Patch und die lesbare Fassung
als JSON auf stdin und erbt die Umgebung des Klassifizierers.

**Das Skript darf scheitern.** Ein Fehler wird protokolliert, beendet aber nicht den Lauf: Die
Klassifizierung ist zu dem Zeitpunkt bereits geschrieben, und eine Zusatzaufgabe darf kein
Dokument unklassifiziert zurücklassen. Ebenso läuft es im Trockenlauf **nicht** — sonst würde
ein `--dry`-Lauf doch etwas verändern.

## Alternativen

- **Einbauen, konfigurierbar machen.** Verlagert fremde Fachlichkeit in den Kern; jede weitere
  Installation bringt neue Schalter mit.
- **Plugin-System mit Python-Importen.** Mehr Macht, aber der Kern müsste Importfehler, Signaturen
  und Versionen tragen. Ein Unterprozess mit JSON auf stdin hat eine schmalere Fläche und
  funktioniert auch mit Skripten, die gar nicht in Python geschrieben sind.
- **Bei Forks bleiben.** Der Zustand, der diesen Eintrag ausgelöst hat.

## Folgen

Der Kern bleibt überall gleich, das Eigene liegt daneben und ist als solches erkennbar. Der Preis:
eine Prozessgrenze je Dokument und die Pflicht, den Vertrag (stdin-Format, Zeitgrenze, Umgebung)
stabil zu halten. → `deploy/nachbearbeitung-beispiel.py`
