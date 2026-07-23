---
id: ADR-1
type: Decision
title: Grounding gegen den Bestand statt freier Generierung
status: erledigt
tags: [ki, klassifikation, qualitaet]
created: 2026-07-01
---

# ADR-1 — Grounding gegen den Bestand

## Kontext

Ein Sprachmodell kann Dokumenttyp und Korrespondent frei benennen. Das erzeugt zuverlässig
Dubletten („STRATO GmbH" neben „Strato AG" neben „strato") und gelegentlich Erfindungen.

## Entscheidung

Der Klassifizierer arbeitet **gegen den vorhandenen Bestand**: Kandidaten werden per Token-Abgleich
vorgeschlagen, das Modell **wählt** daraus, statt frei zu formulieren.

## Begründung

Die eigentliche Arbeit eines Dokumentenarchivs ist Konsistenz, nicht Kreativität. Ein Modell, das
frei benennt, verlagert die Aufräumarbeit nur nach hinten — und dort ist sie teurer, weil sie
tausend bereits abgelegte Dokumente betrifft.

## Konsequenzen

- Ein neuer Korrespondent entsteht bewusst, nicht als Nebenwirkung.
- Der Abgleich braucht eine gepflegte Aliasliste; das ist der Preis.
