# Changelog

Alle nennenswerten Änderungen an diesem Projekt. Das Format folgt lose
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen
[Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt — vier Panel-Blöcke (T-1)

- **Einstellungen** (`/einstellungen`): alle Konfigurationswerte in der Oberfläche, mit passendem
  Eingabeelement je Typ. Der Typ wird aus dem aktuellen Wert abgeleitet — ein neuer Schlüssel
  erscheint von selbst, statt vergessen zu werden. Schlüsselfelder bleiben ausgespart.
  Formulareingaben werden **typsicher** zurückgewandelt (`"350"` → `350`, `"0,2"` → `0.2`); was
  sich nicht umwandeln lässt, wird **übergangen und gemeldet** statt geraten.
- **Korrespondenten zusammenführen**: Mehrfachauswahl, Dokumente umhängen, Dubletten löschen.
  Die Metadaten werden verschmolzen — das Ziel behält seine Werte, leere Felder werden gefüllt,
  Domains und Aliase **vereinigt** (sonst legt der Feedback-Loop den Korrespondenten neu an).
- **Verlauf** (30 Tage) mit Auffälligkeiten-Liste. Lücken werden aufgefüllt: „seit drei Wochen
  läuft nichts" sieht man nur mit leeren Tagen. Ein Fehler gilt als gelöst, wenn für dasselbe
  Dokument **später** ein erfolgreicher Lauf steht.
- **Trace-Ansicht** (`/trace/{id}`): der Lauf in fünf aufklappbaren Schritten statt als
  JSON-Block. Bei der Fehlersuche ist die Frage fast immer „an welcher Stelle ist es gekippt".

### Hinzugefügt — Naht für installationseigene Schritte

Ein optionaler Konfigurationsschlüssel `nachbearbeitung` nennt ein Skript, das **nach** dem
Writeback läuft und Dokument-ID, Erfolg, Patch und die lesbare Fassung als JSON auf stdin
bekommt. Damit braucht eine Installation, die mehr will als Klassifizierung — eine Verknüpfung
in ein Fremdsystem, hauseigene Regeln —, keinen Fork mehr. Genau daraus waren mehrere
auseinanderlaufende Stände desselben Codes entstanden.

Das Skript **darf scheitern**: ein Fehler wird protokolliert, beendet aber nicht den Lauf (die
Klassifizierung ist dann bereits geschrieben). Im Trockenlauf läuft es nicht.
→ `deploy/nachbearbeitung-beispiel.py`, Begründung in `backlog/ADR-3-naht-statt-fork.md`.

### Behoben

- **`build_cfs` vermischte drei Feld-Semantiken** und machte dadurch zwei Dinge falsch, die der
  länger laufende Produktivstand richtig macht:
  - Die **Zusammenfassung landete zweimal** in der `custom_fields`-Liste — einmal mit dem alten Wert
    aus der Schleife, einmal mit dem neuen am Ende.
  - Das **Hinweisfeld wurde nie geleert.** Der Aufrufer setzte `{<Hinweisfeld>: None}`, aber die
    Prüfung auf `skip_fids` griff vorher und behielt den alten Wert. Da der Redo-Trigger auf
    „Hinweisfeld ist befüllt" hört, hätte er nach jeder Verarbeitung erneut gefeuert.

  Ursache war eine: `skip_fids` konnte nur *behalten*, musste aber auch *leeren* und *ersetzen*
  abbilden. Neu ist dafür ein eigener Kanal `code_flds={fid: wert}` — was der Klassifizierer selbst
  setzt, getrennt von dem, was die KI vorschlägt. `None` entfernt die Feldzuordnung. Der eigene Kanal
  sorgt nebenbei dafür, dass ein halluzinierter Feldname der KI **kein** geschütztes Feld erreichen
  kann; bisher schützte nur, dass solche Felder gar nicht erst im Prompt stehen.

- **`build_cfs` war ungetestet** — als einzige Funktion, die entscheidet, *was* geschrieben wird,
  und ohne Netz prüfbar. Neun Fälle ergänzt (beide Regressionen, die gewohnten Wege
  BEHALTEN/null/neuer Wert, und dass ein manuelles Feld auch dann geschützt bleibt, wenn die KI
  seinen Namen nennt).

### Geändert — Icon und Bildnachweis

Das Projektbild ist jetzt ein Papierschiffchen (`docs/paperlaiss.png`) statt der bisherigen
Klorolle. Bildnachweis entsprechend auf **Magnific** umgestellt, in beiden Sprachfassungen.

### Behoben — Backlog-Index las sich falsch

Ein Meilenstein **ohne** Aufgaben bekam im generierten `backlog/README.md` die Zeile
`… — — erledigt` (leere Quote plus das Wort „erledigt"). Der offene Meilenstein M-1 sah damit
aus wie ein abgeschlossener. Steht jetzt als „noch keine Aufgaben" da, mit einer Prüfung
in der Hygiene-Suite.

### Hinzugefügt — Backlog im Repo (`backlog/`)

Meilensteine, Aufgaben und **Entscheidungen (ADR)** liegen als Markdown mit Frontmatter unter
`backlog/`, geprüft von der Testsuite (`python3 scripts/_backlog.py list|check|index`).
Verworfene Entscheidungen werden nicht gelöscht, sondern bekommen `status: verworfen` und
`superseded_by`.

### Geändert

- **Geteilte Testbasis auf repokit 0.7.0** (`repokit sync`, von 0.6.1): bringt
  `tests/_kit/headers.py` mit — Prüfungen für Security-Header und Cookie-Flags. paperlaiss setzt
  derzeit keine eigenen Cookies, die Datei liegt für später bereit. Der Sync zieht außerdem die
  Sperrlisten auf den Stand von 0.7.0 nach (ein Namens-Hash weniger, aus 0.6.2).

### Hinzugefügt

- **Bildnachweis** fürs Logo (`docs/toilet-roll.png`) im README beider Sprachfassungen: Link auf die
  Flaticon-Autorenseite (Creaticca Creative Agency), öffnet in neuem Tab, im Format
  `Icon: … PNG Image by … - flaticon.com`. `flaticon.com` ist damit ein erlaubter Attributions-Host
  in der Hygiene.

## [0.1.0] - 2026-07-12

> **Nicht veröffentlicht.** Diese Version beschreibt den Stand vom 2026-07-12 und entspricht der
> Versionsnummer in `pyproject.toml`, aber es wurde **kein Tag und kein Release gezogen** — das ist
> Absicht, solange das Projekt den WIP-Banner trägt. Der erste Tag folgt, wenn es etwas Releasbares
> gibt; bis dahin ist `main` der Stand.

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
