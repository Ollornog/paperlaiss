# Security Policy

<b>English</b> · <a href="i18n/SECURITY.de.md">Deutsch</a>
<br /><br />

## Reporting a vulnerability

Please report privately through GitHub's
[private vulnerability reporting](https://github.com/Ollornog/paperlaiss/security/advisories/new)
rather than opening a public issue. Expect a first reply within a week.

## Scope and design decisions worth knowing

- **Secrets come from the environment, never the config or the repo.** `PAPERLESS_TOKEN` and
  `MISTRAL_KEY` are read from environment variables; the config keys `api_key_text` / `api_key_ocr`
  exist only as an override and default to empty. A committed `classify-config.json` carries no
  credentials.
- **The classifier writes to Paperless with a full API token.** Give it a token scoped to what it
  needs. It edits type, correspondent, custom fields, the date and — only when `tagging_enabled` —
  tags; it never touches owner or permissions by design.
- **Document text is sent to a third party.** Grounding and OCR call the Mistral API, so document
  content leaves your machine. That is the point of the tool, but it is a data-flow decision worth
  making consciously; `content_max_len` bounds how much is sent.
- **The panel is unauthenticated unless you set `PANEL_TOKEN`.** Without it the dashboard, the JSON
  API and the reclassify action are open to anyone who reaches the port. In production put a reverse
  proxy with forward-auth or OIDC in front of it, and bind the port to the internal network.
- **Ingest tokens are capabilities.** Each entry in `INGEST_TOKENS` lets its holder push a document
  into Paperless with a fixed source tag. Treat them like passwords, one per intake, and rotate a
  leaked one by editing the map.
- **`reserved_tags` are protected on write-back.** Status, direction and marker tags in that list
  are never assigned by the model and are preserved when metadata is patched.

## Not in scope

Anything the operator can do by design (point the token at any document, send any content to the
model), and denial of service through very large uploads or documents.

<br /><br />
<p align="right"><img src="docs/toilet-roll.png" alt="paperlaiss" width="60" height="60"></p>
