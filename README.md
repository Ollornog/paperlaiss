<p align="center"><img src="docs/toilet-roll.png" alt="paperlaiss" width="250" height="250"></p>

<h1 align="center">paperlaiss</h1>

<p align="center"><b>English</b> · <a href="i18n/README.de.md">Deutsch</a></p>

<p align="right">
<a href="https://github.com/Ollornog/paperlaiss/actions/workflows/ci.yml"><img src="https://github.com/Ollornog/paperlaiss/actions/workflows/ci.yml/badge.svg" alt="tests"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-informational.svg" alt="License: MIT"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python">
</p>

### A grounded document classifier for Paperless-ngx.

A lean, self-contained replacement for [paperless-ai](https://github.com/clusterzx/paperless-ai).
It runs as a `POST_CONSUME_SCRIPT` (or by hand, or from the panel) and writes metadata straight
back through the Paperless REST API.

The classifier is **stdlib-only** — no packages to install — and **tenant-agnostic**: every field
and tag is resolved by *name* against the API, and every behaviour is a switch in the config. An
optional FastAPI panel adds a dashboard and an ingest endpoint.

---

## What it does

- **Document type** and **correspondent**, with a **feedback loop** against what already exists
  (token match plus an LLM pass) that prevents duplicates and hallucinations — no "STRATO GmbH"
  next to "Strato".
- **Custom fields** filled type-correctly, three ways per field: a value, `null` to clear it, or
  `BEHALTEN` ("keep") when the model is unsure.
- **OCR rescue**: weak or garbage text is re-read with **Mistral OCR** — automatically, or on the
  model's own request.
- **Document date** corrected to the real issue date, not a date merely referenced in the body.
- **Self-repair**: on an API validation error the model fixes its own field values in a ping-pong
  loop until the `PATCH` lands.
- Optional, per config: content **tagging**, an adaptive **summary**, **redo from Paperless** (a
  trigger tag plus a hint field), and **origin context** (a mail or chat cover note).

**Deliberately out of scope:** owner and permission assignment (that stays with the Paperless
consume path / `post-consume.sh`), contract and device links, tax automation — those are
tenant-specific.

## Setup

1. **Secrets as environment variables** (never in the config or the repo):
   ```bash
   export PAPERLESS_TOKEN=<paperless-api-token>
   export MISTRAL_KEY=<mistral-api-key>
   ```
2. Adjust **`classify-config.json`** (model, `tagging_enabled`, `marker_tag`, `reserved_tags`, …).
3. Wire it in as a post-consume script in Paperless:
   ```
   PAPERLESS_POST_CONSUME_SCRIPT=/path/to/classify.py
   ```
   (Paperless sets `DOCUMENT_ID`.) The Python standard library is enough — no extra packages.

## Manual runs and testing

```bash
CLASSIFY_DRY=1  CLASSIFY_DOC=<id>  python3 classify.py     # print only, write nothing
CLASSIFY_FORCE=1 CLASSIFY_DOC=<id> python3 classify.py     # redo an already-classified document
CLASSIFY_FORCE_OCR=1 CLASSIFY_DOC=<id> python3 classify.py # force Mistral OCR
```

## Panel

A lean **FastAPI dashboard** (a standalone building block, not a fork), meant to run as its own
container in the same Docker network, sharing the `scripts/` volume:

- **Dashboard** (`/`) — live status ("running now"), counters (classified / OCR rescues / repaired
  / errors / skipped), an activity feed where every document ID opens a **trace inspector**.
- **Classify manually** — a document ID, reclassified or forced through OCR.
- **JSON API**: `/api/stats`, `/api/feed`, `/api/running`, `/api/trace/{id}`, `/api/reclassify`,
  `/api/config` (GET/POST). A higher-level platform can consume the same endpoints.
- **Protection**: an optional `PANEL_TOKEN` (bearer/cookie). Otherwise put a reverse proxy with
  forward-auth or OIDC in front of it in production.

## Ingest API

`POST /ingest` (multipart `file` plus an optional `title`, header `X-Ingest-Token`) hands the file
to Paperless `post_document` and attaches a **source tag**. One token per intake (`INGEST_TOKENS`),
named by place or person (`Scan office`, `Scan workshop`). External scanners can then deliver
documents on their own, carrying their origin, and the classifier receives that source tag.

```bash
curl -F "file=@scan.pdf" -H "X-Ingest-Token: secret-office-scanner" http://panel:8400/ingest
```

## Correspondent metadata

Paperless **cannot** natively extend correspondents with fields (custom fields hang off documents
only). paperlaiss solves this with its **own store** (`correspondents.json`, edited in the panel),
keyed **by Paperless correspondent ID** so it survives a rename. Per correspondent: `email`,
`domains`, `phone`, `address`, `customer_number`, `vat_id`, `context`, `aliases`.

Edited in the panel under **`/korrespondenten`** (all correspondents plus an edit dialog). The
classifier uses it for grounding: `domains` to match senders, `context` and the identifiers in the
prompt, `aliases` in the feedback loop — sharper classification.

## Deployment (Docker)

See [`deploy/docker-compose.example.yml`](deploy/docker-compose.example.yml) and
[`deploy/.env.example`](deploy/.env.example): extend your existing `paperless` service with the
`./scripts` volume, `POST_CONSUME` and the `CLASSIFY_*` variables, and add the `panel` service.
`scripts/` must be writable by both containers.

## Configuration (`classify-config.json`)

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | classifier on/off |
| `model` / `ocr_model` | `mistral-small-latest` / `mistral-ocr-latest` | Mistral models |
| `ocr_enabled` / `ocr_always` / `ocr_min_len` | `true` / `false` / `300` | OCR rescue behaviour |
| `tagging_enabled` | `false` | AI assigns content tags (off: type/correspondent/fields only) |
| `marker_tag` | `ai-processed` | tag written, and used as the "already done" signal |
| `unsicher_tag` / `redo_tag` | – | optional flag / redo tags (by name) |
| `summary_field` / `hinweis_field` / `mail_context_field` / `mail_from_field` | – | optional fields (by name) |
| `reserved_tags` | `[]` | tag names the AI never assigns (status / direction / marker) |
| `system_prompt` | – | empty = built-in prompt (`{TYPES}` / `{TAGBLOCK}` are substituted) |
| `tag_descriptions` | `{}` | per-tag descriptions (only when tagging is on) |
| `api_key_text` / `api_key_ocr` | – | empty = `MISTRAL_KEY` from the environment |

## Development

```bash
./scripts/check.sh          # unit + hygiene tests
git config core.hooksPath .githooks
```

The classifier is stdlib-only; the tests exercise its pure helpers and need no network. The suite
is **repeatable**: running it twice must be green twice. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security

Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).

## Licence

[MIT](LICENSE)

## Credits

Icon: <a href="https://www.flaticon.com/authors/creaticca-creative-agency" target="_blank" rel="noopener">Toilet Paper PNG Image by Creaticca Creative Agency - flaticon.com</a>
