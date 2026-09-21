---
id: T-2
type: Task
title: Alle Installationen auf den Repo-Stand bringen
status: offen
milestone: M-1
tags: [betrieb, wartbarkeit]
created: 2026-09-21
---

# T-2 — Alle Installationen auf den Repo-Stand bringen

Es existieren mehrere auseinandergelaufene Stände desselben Klassifizierers. Das ist die
teuerste Altlast des Projekts: jeder Fehler muss mehrfach behoben werden, und ein Fix im Repo
erreicht eine laufende Installation nicht.

**Warum es überhaupt dazu kam:** Der Klassifizierer konnte nichts, was nur eine Installation
braucht — also wurde er kopiert und erweitert. Die Naht `nachbearbeitung` (→ ADR-3) macht das
überflüssig; sie ist die Voraussetzung für diesen Task, nicht ein Nebenprodukt.

**Vorgehen je Installation:**

1. Installationseigenen Prompt aus dem Code in `classify-config.json` (`system_prompt`) heben —
   **vor** dem Einspielen, sonst misst man mit einem Prompt, der den Bestand nicht kennt.
2. Eigene Zusatzlogik in ein Skript ziehen und als `nachbearbeitung` eintragen.
3. Harte Kennungen durch die Namensauflösung ersetzen (`resolve_tag`/`resolve_field`).
4. Repo-Stand einspielen, an einem Wegwerf-Dokument prüfen.

**Fertig, wenn** jede Installation denselben `classify.py` fährt und sich ausschließlich über
Konfiguration und Nachbearbeitung unterscheidet.
