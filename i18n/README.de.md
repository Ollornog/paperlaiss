<p align="center"><img src="../docs/toilet-roll.png" alt="paperlaiss" width="250" height="250"></p>

<h1 align="center">paperlaiss</h1>

<p align="center"><a href="../README.md">English</a> · <b>Deutsch</b></p>

<p align="right">
<a href="https://github.com/Ollornog/paperlaiss/actions/workflows/ci.yml"><img src="https://github.com/Ollornog/paperlaiss/actions/workflows/ci.yml/badge.svg" alt="tests"></a>
<a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-informational.svg" alt="License: MIT"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python">
</p>

### Ein grounded Dokumenten-Klassifizierer für Paperless-ngx.

Ein schlanker, eigenständiger Ersatz für [paperless-ai](https://github.com/clusterzx/paperless-ai).
Läuft als `POST_CONSUME_SCRIPT` (oder manuell / per Panel) und schreibt Metadaten direkt über die
Paperless-REST-API zurück.

Der Klassifizierer ist **stdlib-only** — keine Pakete zu installieren — und **mandantenunabhängig**:
jedes Feld und jeder Tag wird per *Name* gegen die API aufgelöst, jedes Verhalten ist ein Schalter
in der Config. Ein optionales FastAPI-Panel bringt Dashboard und Ingest-Endpunkt dazu.

---

## Was es kann

- **Dokumenttyp** und **Korrespondent** — mit **Feedback-Loop** gegen den Bestand (Token-Match plus
  LLM-Auflösung), der Dubletten und Halluzinationen verhindert — kein „STRATO GmbH" neben „Strato".
- **Custom-Fields** typgerecht gefüllt, drei Wege je Feld: ein Wert, `null` zum Leeren oder
  `BEHALTEN`, wenn das Modell unsicher ist.
- **OCR-Rescue**: schwacher oder Müll-Text wird per **Mistral-OCR** neu gelesen — automatisch oder
  auf Anforderung des Modells.
- **Dokumentdatum** korrigiert auf das echte Ausstellungsdatum, nicht ein bloß im Text erwähntes.
- **Self-Repair**: bei einem API-Validierungsfehler korrigiert das Modell seine Feldwerte in einer
  Ping-Pong-Schleife, bis der `PATCH` sitzt.
- Optional, per Config: inhaltliches **Tagging**, adaptive **Zusammenfassung**, **Redo aus
  Paperless** (Trigger-Tag plus Hinweis-Feld) und **Herkunft-Kontext** (Mail-/Chat-Anschreiben).

**Bewusst nicht enthalten:** Owner- und Rechtevergabe (bleibt beim Paperless-Konsumpfad /
`post-consume.sh`), Vertrags- und Geräte-Verknüpfungen, Steuer-Automatik — das ist
mandantenspezifisch.

## Setup

1. **Secrets als Umgebungsvariablen** (nie in die Config oder ins Repo):
   ```bash
   export PAPERLESS_TOKEN=<paperless-api-token>
   export MISTRAL_KEY=<mistral-api-key>
   ```
2. **`classify-config.json`** anpassen (Modell, `tagging_enabled`, `marker_tag`, `reserved_tags`, …).
3. In Paperless als Post-Consume einhängen:
   ```
   PAPERLESS_POST_CONSUME_SCRIPT=/pfad/classify.py
   ```
   (Paperless setzt `DOCUMENT_ID`.) Die Python-Standardbibliothek genügt — keine Extra-Pakete.

## Manuell und testen

```bash
CLASSIFY_DRY=1  CLASSIFY_DOC=<id>  python3 classify.py     # nur ausgeben, nichts schreiben
CLASSIFY_FORCE=1 CLASSIFY_DOC=<id> python3 classify.py     # schon klassifiziertes Dokument neu machen
CLASSIFY_FORCE_OCR=1 CLASSIFY_DOC=<id> python3 classify.py # Mistral-OCR erzwingen
```

## Panel

Ein schlankes **FastAPI-Dashboard** (ein eigenständiger Baustein, kein Fork), gedacht als eigener
Container im selben Docker-Netz, das sich das `scripts/`-Volume teilt:

- **Dashboard** (`/`) — Live-Status („läuft gerade"), Kennzahlen (klassifiziert / OCR-Rescues /
  repariert / Fehler / übersprungen), ein Aktivitäts-Feed, in dem jede Doc-ID einen
  **Trace-Inspektor** öffnet.
- **Manuell klassifizieren** — eine Doc-ID, neu klassifiziert oder per OCR erzwungen.
- **JSON-API**: `/api/stats`, `/api/feed`, `/api/running`, `/api/trace/{id}`, `/api/reclassify`,
  `/api/config` (GET/POST). Eine übergeordnete Plattform kann dieselben Endpunkte konsumieren.
- **Schutz**: optional ein `PANEL_TOKEN` (Bearer/Cookie). Sonst in Prod einen Reverse-Proxy mit
  Forward-Auth oder OIDC davorsetzen.

## Ingest-API

`POST /ingest` (multipart `file` plus optional `title`, Header `X-Ingest-Token`) reicht die Datei
an Paperless `post_document` und hängt ein **Quelle-Tag** an. Ein Token je Eingang (`INGEST_TOKENS`),
benannt nach Ort oder Person (`Scan Büro`, `Scan Werkstatt`). So liefern externe Scanner selbst
Dokumente ab, samt Herkunft, und der Klassifizierer erhält das Quelle-Tag.

```bash
curl -F "file=@scan.pdf" -H "X-Ingest-Token: geheim-scanner-buero" http://panel:8400/ingest
```

## Korrespondent-Metadaten

Paperless **kann** Korrespondenten nativ nicht um Felder erweitern (Custom Fields hängen nur an
Dokumenten). paperlaiss löst das mit einem **eigenen Store** (`correspondents.json`, im Panel
gepflegt), gebunden **per Paperless-Korrespondent-ID**, sodass er eine Umbenennung übersteht. Pro
Korrespondent: `email`, `domains`, `telefon`, `adresse`, `kundennummer`, `uid`, `kontext`, `aliase`.

Gepflegt im Panel unter **`/korrespondenten`** (alle Korrespondenten plus Edit-Modal). Der
Klassifizierer nutzt das fürs Grounding: `domains` zur Absender-Zuordnung, `kontext` und die
Kennungen im Prompt, `aliase` im Feedback-Loop — präzisere Klassifizierung.

## Deployment (Docker)

Siehe [`deploy/docker-compose.example.yml`](../deploy/docker-compose.example.yml) und
[`deploy/.env.example`](../deploy/.env.example): den bestehenden `paperless`-Service um das
`./scripts`-Volume, `POST_CONSUME` und die `CLASSIFY_*`-Variablen erweitern und den `panel`-Service
ergänzen. `scripts/` muss für beide Container schreibbar sein.

## Konfiguration (`classify-config.json`)

| Key | Default | Bedeutung |
|---|---|---|
| `enabled` | `true` | Klassifizierer an/aus |
| `model` / `ocr_model` | `mistral-small-latest` / `mistral-ocr-latest` | Mistral-Modelle |
| `ocr_enabled` / `ocr_always` / `ocr_min_len` | `true` / `false` / `300` | OCR-Rescue-Verhalten |
| `tagging_enabled` | `false` | KI vergibt inhaltliche Tags (aus: nur Typ/Korrespondent/Felder) |
| `marker_tag` | `ai-processed` | Tag, das gesetzt wird + als „schon erledigt"-Signal dient |
| `unsicher_tag` / `redo_tag` | – | optionale Flag-/Redo-Tags (per Name) |
| `summary_field` / `hinweis_field` / `mail_context_field` / `mail_from_field` | – | optionale Felder (per Name) |
| `reserved_tags` | `[]` | Tag-Namen, die die KI nie vergibt (Status / Richtung / Marker) |
| `system_prompt` | – | leer = eingebauter Prompt (`{TYPES}` / `{TAGBLOCK}` werden ersetzt) |
| `tag_descriptions` | `{}` | Beschreibungen je Tag (nur bei aktivem Tagging) |
| `api_key_text` / `api_key_ocr` | – | leer = `MISTRAL_KEY` aus der Umgebung |

## Entwicklung

```bash
./scripts/check.sh          # Fach- und Hygiene-Tests
git config core.hooksPath .githooks
```

Der Klassifizierer ist stdlib-only; die Tests prüfen seine reinen Hilfsfunktionen und brauchen kein
Netz. Die Suite ist **wiederholbar**: zweimal laufen lassen muss zweimal grün sein. Siehe
[`CONTRIBUTING.de.md`](CONTRIBUTING.de.md).

## Sicherheit

Schwachstellen bitte vertraulich melden — siehe [`SECURITY.de.md`](SECURITY.de.md).

## Lizenz

[MIT](../LICENSE)

## Bildnachweis

Icon: <a href="https://www.flaticon.com/authors/creaticca-creative-agency" target="_blank" rel="noopener">Toilet Paper PNG Image by Creaticca Creative Agency - flaticon.com</a>
