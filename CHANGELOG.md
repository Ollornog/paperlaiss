# Changelog

Alle nennenswerten Änderungen an diesem Projekt. Das Format folgt lose
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen
[Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt

- **Bildnachweis** fürs Logo (`docs/toilet-roll.png`) im README beider Sprachfassungen: Link auf die
  Flaticon-Autorenseite (Creaticca Creative Agency), öffnet in neuem Tab, im Format
  `Icon: … PNG Image by … - flaticon.com`. `flaticon.com` ist damit ein erlaubter Attributions-Host
  in der Hygiene.

## [0.1.0] - 2026-07-12

### Hinzugefügt

- **Klassifizierer** (`classify.py`): grounded Dokumenten-Klassifizierer für Paperless-ngx als
  Ersatz für paperless-ai. Stdlib-only, mandantenunabhängig (Feld-/Tag-Auflösung per Name).
  Dokumenttyp und Korrespondent mit Feedback-Loop gegen Dubletten, typgerechte Custom-Fields
  (Wert / `null` / `BEHALTEN`), OCR-Rescue via Mistral, Dokumentdatum-Korrektur, Self-Repair-Loop
  und optionales Tagging/Summary/Redo/Herkunft-Kontext.
- **Panel** (`panel/`): schlankes FastAPI-Dashboard mit Live-Status, Kennzahlen, Trace-Inspektor,
  manuellem Klassifizieren, JSON-API und Korrespondent-Metadaten-Store; optionaler `PANEL_TOKEN`.
- **Ingest-API**: `POST /ingest` reicht externe Scans an Paperless durch und vergibt ein Quelle-Tag,
  ein Token je Eingang.
- **Repo-Gerüst** nach dem Bootstrap der übrigen öffentlichen Repos: MIT-Lizenz, zweisprachige
  Doku (Root Englisch, Übersetzungen unter `i18n/`), Verhaltenskodex, Sicherheitsrichtlinie,
  Mitwirken-Leitfaden, geteilte Testbasis (`tests/_kit/`), gehärtete Workflows (SHA-gepinnte
  Actions, `permissions:`, `ubuntu-latest`) und Dependabot.
