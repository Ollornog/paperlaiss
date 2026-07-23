---
id: ADR-2
type: Decision
title: Eigener Klassifizierer statt vorhandener Erweiterung
status: erledigt
tags: [architektur, ki]
created: 2026-07-01
---

# ADR-2 — Eigener Klassifizierer

## Kontext

Für Paperless-ngx gibt es fertige KI-Erweiterungen. Eine davon war im Einsatz.

## Entscheidung

**Eigenen Klassifizierer bauen.**

## Begründung

Drei Dinge ließen sich in der fremden Lösung nicht erreichen, ohne sie zu forken: der Abgleich
gegen den Bestand ([ADR-1](ADR-1-grounding-statt-freier-generierung.md)), ein nachvollziehbares
Protokoll jeder Entscheidung, und eine Rückkopplung, mit der sich Fehlklassifikationen korrigieren
lassen, ohne alles neu zu verarbeiten.

## Konsequenzen

- Wartung liegt bei uns — inklusive der Anpassung an neue Paperless-Versionen.
- Dafür ist jede Entscheidung im Protokoll nachlesbar statt eine Blackbox.
