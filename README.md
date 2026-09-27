<p align="center"><img src="panel/paperlaiss.png" alt="paperlaiss" width="250" height="250"></p>

<h1 align="center">paperlaiss</h1>

<p align="center"><b>English</b> · <a href="i18n/README.de.md">Deutsch</a></p>

<p align="right">
<a href="https://github.com/Ollornog/paperlaiss/actions/workflows/ci.yml"><img src="https://github.com/Ollornog/paperlaiss/actions/workflows/ci.yml/badge.svg" alt="tests"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-informational.svg" alt="License: MIT"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python">
</p>

> 🚧 **Work in progress** — under active development; interfaces and structure may still change before a stable `1.0` release.

### A grounded document classifier for Paperless-ngx.

A lean, self-contained replacement for [paperless-ai](https://github.com/clusterzx/paperless-ai).
It runs as a `POST_CONSUME_SCRIPT` (or by hand, or from the panel) and writes metadata straight
back through the Paperless REST API.

The classifier is **stdlib-only** — no packages to install — and **tenant-agnostic**: every field
and tag is resolved by *name* against the API, and every behaviour is a switch in the config. An
optional FastAPI panel adds an admin view and an ingest endpoint.

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
   Supported are the three most recent stable Python releases (currently 3.12–3.14); the minimum
   rises with each new Python release on purpose.

## Manual runs and testing

```bash
CLASSIFY_DRY=1  CLASSIFY_DOC=<id>  python3 classify.py     # print only, write nothing
CLASSIFY_FORCE=1 CLASSIFY_DOC=<id> python3 classify.py     # redo an already-classified document
CLASSIFY_FORCE_OCR=1 CLASSIFY_DOC=<id> python3 classify.py # force Mistral OCR
```

A document type that is already set is replaced only on a real import (no `CLASSIFY_SOURCE`, no
`CLASSIFY_FORCE`), by the button in Paperless and from the panel. Manual runs with `CLASSIFY_FORCE`
and bulk runs (`CLASSIFY_SOURCE=bulk`) leave it alone — a person may have set it. A type that
Paperless' own matching pre-set on import reaches the model as a suggestion.

## Panel

An admin panel for when something hangs or needs adjusting — paperlaiss is middleware, master data
(tags, correspondents) stays in Paperless or your own system. A FastAPI container in the same
Docker network, sharing the `scripts/` volume. Its look comes from the
[C22](https://github.com/Ollornog/C22) design system, vendored under `panel/static/c22/`
(`scripts/vendor-c22.sh`); `tests/test_c22_klassen.py` checks every class against it.

- **Activity** (`/`) — five counters and a 30-day chart that **filter** the list (the filter lives in
  the address, so *Back* undoes it), 100 entries per page. A row opens the **run**: decision tree,
  prompt, AI output, and the OCR text rendered as Markdown.
- **Flow & prompt** (`/ablauf`) — every step a document goes through, each with its input and output
  to expand; for the AI calls the prompt and the answer format. The Pass-1 prompt is editable in
  place and also shown exactly as it is sent (`CLASSIFY_PROMPT_VORSCHAU=1`). A run in the activity
  list is shown with the same steps and its real prompts and answers.
- **Info** (`/info`) — what paperlaiss is, links to the repository and the building blocks.
- **Settings** (`/einstellungen`) — every value of the effective configuration (file plus defaults;
  saving writes only the changed keys).
- **Classify manually** — a document ID, reclassified or forced through OCR.
- **JSON API**: `/api/aktivitaet`, `/api/verlauf`, `/api/running`, `/api/trace/{id}`,
  `/api/reclassify`, `/api/config` (GET/POST), `/api/prompt-vorschau` (GET; POST with a draft for the live preview while editing).
- **Sign-in** (`PANEL_AUTH`):
  - empty (default) — bearer token / cookie `PANEL_TOKEN`; without a token the panel answers 503.
  - `none` — no sign-in of its own, because one sits in front of it (reverse proxy with forward-auth).
  - `tinysesam` — its own sign-in page via [TinySesam](https://github.com/Ollornog/TinySesam):
    OIDC (e.g. PocketID) through `PANEL_OIDC_ISSUER`, `PANEL_OIDC_CLIENT_ID`,
    `PANEL_OIDC_CLIENT_SECRET` (optional `PANEL_OIDC_GROUPS`, `PANEL_OIDC_NAME`); username + password
    only with `PANEL_PASSWORD_LOGIN=1` (meant for a test instance), first account from
    `PANEL_ADMIN_USER` / `PANEL_ADMIN_PASSWORD`. Required: `PANEL_BASE_URL` (the address browsers
    use); the user store lives in `PANEL_AUTH_DB` (default `/auth/tinysesam.db`, mount it as a
    volume). A half-configured OIDC or no sign-in method at all stops the container with a message.
    A set `PANEL_TOKEN` stays valid for scripts. Behind a reverse proxy set `PANEL_TRUSTED_PROXIES`
    (comma-separated networks of **every** proxy in the chain, e.g. the Docker network
    `172.16.0.0/12` plus an upstream proxy) — otherwise all users share the proxy's IP and rate
    limiting, lockout and the audit log apply to everyone at once.
- **Under a sub-path** (e.g. `https://paperless.example.com/paperlaiss`, next to Paperless on the same
  domain): set `PANEL_PFAD=/paperlaiss` and let the reverse proxy strip the prefix (Caddy:
  `handle_path /paperlaiss/* { reverse_proxy panel:8400 }`). The panel prefixes every link and API
  call, and starts uvicorn with `--root-path`. With TinySesam, `PANEL_BASE_URL` must end in the same
  path — otherwise the container refuses to start.

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
`domains`, `telefon`, `adresse`, `kundennummer`, `ustid`, `iban`, `kontext`, `aliase`; the identifiers
(e-mail, domains, phone, customer number, VAT ID, IBAN, aliases) can hold several values each. Phone
numbers are stored without spaces and without guessing a country: `+49 (0) 30 …` and `0049 30 …`
become `+4930…`, a national `030 …` stays `030…`. The search matches both forms via the number
without country code and trunk zero; two international numbers must match completely.

Edited **in Paperless itself**: the buttons script adds a section *paperlaiss* to the correspondent
edit dialog (context, aliases, e-mail, mail domains, customer number, VAT ID, phone, address; each
value of a list field as a line with edit and delete, a new one via the input with „+“),
saved together with Paperless' *Save* — allowed for whoever may change that correspondent in
Paperless. The file can also be filled from outside (your master data system, a script). The
classifier uses it in three ways:

- **Finding candidates, without an LLM call.** Before the analysis, paperlaiss searches the text for
  the stored identifiers of *all* correspondents (VAT ID, IBAN, e-mail, domain, customer number) and,
  in the letterhead (first 1000 characters), for their names and aliases. A document that came by
  mail also counts its sender address. Everything found goes to the analysis as a candidate, with
  context and where it was found. The mail sender is a strong candidate, not an assignment: a portal
  sends documents of many companies from one address. (Until 2026-09-27 a separate LLM call —
  "Pass 0" — guessed a sender name first; the search replaces it.)
- **Own company or household.** `eigene_kennungen` (names, VAT IDs, IBANs, mail domains/addresses)
  never count as a sender: they appear on almost every incoming document. The analysis is told who
  "we" are and to look for the *counterpart*. The built-in rule for that is written for a company
  (customers, outgoing invoices, payroll); `eigene_regel` replaces it — a household names its own
  cases there (own letters, CV, a power of attorney between members). `{ERSTER}` inserts the first
  own name.
- **Filling in master data.** `stammdaten_erfassen` (on by default): after assignment, the
  counterpart's VAT ID, IBAN, e-mail/domain, phone, address and customer number from the document
  fill empty fields; IBAN, e-mail, domain, phone and customer number are **appended** as a further
  value when the analysis named the correspondent exactly (at most 10 per field). Nothing is ever
  overwritten; VAT ID and address stay single (a second VAT ID is reported, not stored); a value that
  already belongs to another correspondent is dropped, so one wrong assignment cannot pull later
  documents to the wrong correspondent. The origin (`erfasst`, per value for list fields) is shown in
  the Paperless dialog. The mail sender is only taken over if it demonstrably belongs to that
  correspondent. Writes are serialised with a file lock shared with the panel.
- **Matching the name.** If the name from the analysis matches no correspondent exactly, a second
  message in the same conversation ("Pass 2") asks which similar correspondent is meant — only for
  similar names that pass a fixed name rule (the name is contained in the other, typos only in long
  words; persons: same last *and* first name; otherwise a rare shared word of 6+ letters). If none
  passes, a new correspondent is created without a second call. The rule alone never assigns:
  measured against two real name lists it would have merged 10–18 % of the names into a different
  correspondent.

## Deployment (Docker)

See [`deploy/docker-compose.example.yml`](deploy/docker-compose.example.yml) and
[`deploy/.env.example`](deploy/.env.example): extend your existing `paperless` service with the
`./scripts` volume, `POST_CONSUME` and the `CLASSIFY_*` variables, and add the `panel` service.
`scripts/` must be writable by both containers.

### Buttons in Paperless (optional)

One **KI** button (magic wand: optional hint, then paperlaiss re-reads the document with Mistral OCR
and re-classifies it) — in the document view instead of Paperless' own *Suggest* (hidden), and as an
entry in the **Actions** menu of the multi-select. No fork, no tags, no workflow:

- Paperless runs scripts from `/custom-cont-init.d` on every container start (*Custom Container
  Initialization*). `deploy/paperless-knoepfe/10-paperlaiss-knoepfe.sh` copies
  `paperlaiss-knoepfe.js` into the static directory and adds one `<script>` line to the start page —
  again after every update, nothing to merge.
- The buttons call the panel directly (`POST /knopf`). The browser sends the **Paperless session**
  along; the panel asks Paperless with it which documents this user may change
  (`user_can_change`) and processes only those. Without a valid session: 401.
- `PAPERLAISS_URL` (Paperless container): where the browser reaches the panel. Behind the same
  reverse proxy a path is enough (default `/paperlaiss`, proxied to the panel without the prefix);
  on a separate port the full address. In that case also set `PAPERLAISS_KNOPF_ORIGIN` (panel
  container) to the Paperless address, so the cross-origin call passes CORS.
- With *Select all* across pages only the visible selected documents are processed, and the menu
  entry says so. The panel runs at most `PANEL_PARALLEL` (default 2) jobs at once. After the run the
  page reloads, so Paperless does not save its stale state back over the result. If Paperless
  changes its page, the buttons are missing — Paperless itself keeps working.

A second entry, **Export**, sits next to it in the **Actions** menu. Its dialog offers two variants:

- **One PDF** — all selected documents merged, one bookmark per document (the source's own
  bookmarks nested below), optional **page numbers** ("Seite i von n") and an optional **table of
  contents** in front: title and page number jump to the document, *In Paperless öffnen* opens it in
  Paperless.
- **Separately** — every document as its own PDF, byte-identical to what Paperless delivers. The file
  name comes from a **template** with `{titel}`, `{korrespondent}`, `{typ}`, `{datum}`, `{jahr}`,
  `{monat}`, `{hinzugefuegt}`, `{id}`, `{asn}`, `{seiten}`, `{original}` and `{feld:<custom field>}`;
  optionally **numbered** (`001_`), optionally as a **ZIP** and with a **table-of-contents PDF** whose
  entries link to the neighbouring files (they work once the ZIP is unpacked) and to Paperless. The
  title is a relative URI (Chrome's PDF viewer follows it, but not a remote go-to); *Datei: …* is the
  same file as a remote go-to for viewers that open files themselves.
- Both can be **sorted** by any variable or custom field, ascending or descending. Source is the
  archive PDF, otherwise the original if it is a PDF; anything else is skipped and listed (in the
  dialog and under *Nicht enthalten* in the table of contents).
- Rights as for the KI button, but **read** permission is enough: the panel checks with the user's
  Paperless session, and one unreadable document rejects the whole export (403) instead of silently
  leaving it out. Status and download check again on every call. Names (correspondent, type, fields)
  are fetched with the user's session as well; the PDFs are downloaded with the panel's token.
- Panel settings: `EXPORT_MAX_DOKUMENTE` (default 1000), `EXPORT_MAX_MB` (2000, sum of the PDFs),
  `EXPORT_PARALLEL` (1), `EXPORT_SPEICHER_MB` (10000 — all finished exports together; the oldest go first), `EXPORT_AUFBEWAHRUNG_MIN` (20 minutes — afterwards the result and its files are
  deleted), `EXPORT_TMP` (temporary directory), `PAPERLESS_PUBLIC_URL` (Paperless address for the
  links; unset: the address of the Paperless page that called, same origin only). Times follow
  `PAPERLESS_TIME_ZONE`, otherwise `TZ`. The panel must run as a single process (jobs live in memory).

### Pre-consume steps: blank pages, mails as documents (optional)

`deploy/vorab/vorab.py` is the entry for `PAPERLESS_PRE_CONSUME_SCRIPT` (Paperless takes only one
script). It runs the steps lying next to it, one after the other; each decides itself whether the
file concerns it, replaces the working copy only at the end and atomically, and everything always
exits 0 — no step ever blocks an import. Stdlib only, plus `gs` and `qpdf` from the Paperless image.

**Blank pages** (`leerseiten.py`, switch `leerseiten_entfernen`, on by default): every page of a PDF
is rendered in greyscale; a page goes only if it is *completely* white — nothing on it but dust
specks under 1 mm. A page number, a tiny counter, a barcode or a line keeps the page. Measured
against a real archive (604 PDFs, 1962 pages): exactly the 11 blank backs go, no page with content.
Never touched: single-page PDFs, encrypted or signed ones, PDFs with embedded files (e-invoices),
and a document whose pages would all go. The result is deterministic, so Paperless still detects a
duplicate by its checksum.

**Mails as documents with header and large images** (`mailbilder.py`) for mail rules that consume the **whole mail** (`.eml`, PDF layout "HTML only"). Before Paperless
renders the mail it adds a small header (from, to, date, subject) and one full-size page per image
in the mail — photos and scans, not logos, banners or social icons (judged by size, aspect ratio and
name; measured against a real mailbox: 2 of 37 inline images kept, all logos dropped). Images in
the mail body are shown as a preview; every part gets a Content-ID so Paperless can resolve `cid:`
links. Other files are left untouched, and the script always exits 0 — it never blocks an import.

A setup that never loses an attachment and never files a logo on its own: rule 1 consumes real
attachments (all types), rule 2 inline PDFs (`attachment type: everything`, include `*.pdf`), rule 3
the whole mail for everything the first two did not take. Paperless skips a mail in later rules once
an earlier rule consumed it in the same run.

## Configuration (`classify-config.json`)

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | classifier on/off |
| `titel_setzen` | `true` | title "Correspondent – document type identifier"; overwritten like the document type (import, AI button, panel — never in a bulk run) |
| `leerseiten_entfernen` | `true` | remove completely white pages at import (pre-consume step `leerseiten.py`) |
| `model` / `ocr_model` | `mistral-small-latest` / `mistral-ocr-latest` | Mistral models |
| `ocr_enabled` / `ocr_always` / `ocr_min_len` | `true` / `false` / `300` | OCR rescue behaviour |
| `ocr_regeln` | see below | when a text counts as too weak and is re-read by OCR |
| `tagging_enabled` | `false` | AI assigns content tags (off: type/correspondent/fields only) |
| `marker_tag` | `ai-processed` | tag written, and used as the "already done" signal |
| `unsicher_tag` | – | optional flag tag (by name) |
| `summary_field` / `mail_context_field` / `mail_from_field` | – | optional fields (by name) |
| `reserved_tags` | `[]` | tag names the AI never assigns (status / direction / marker) |
| `system_prompt` | – | empty = built-in prompt (`{TYPES}` / `{TAGBLOCK}` are substituted; the older `{TAGS}` gets the bare tag list; with tagging on and neither placeholder, the tag block is appended) |
| `tag_descriptions` | `{}` | per-tag descriptions (only when tagging is on) |
| `api_key_text` / `api_key_ocr` | – | empty = `MISTRAL_KEY` from the environment |

### OCR fallback (`ocr_regeln`)

Two gates decide whether a document is re-read by Mistral OCR:

1. **Before the analysis — rules.** OCR runs if the text is shorter than `min_zeichen`
   (default: `ocr_min_len`), contains fewer than `min_schluesselwoerter` of `schluesselwoerter`,
   has fewer than one real word per `max_zeichen_je_wort` characters, or more than
   `max_muell_anteil` of its visible characters are neither letters, digits nor ordinary
   punctuation.
2. **After the analysis — the AI and optional rules.** If the model reports unreadable text
   (`nach_ki_meldung`, default on) or — when switched on — found no document type
   (`wenn_kein_typ`) or no correspondent (`wenn_kein_korrespondent`), the document is read by
   OCR and analysed again in the same conversation. Only if no OCR ran before, so a document is
   never paid for twice.

**Re-classifying from Paperless** (redo tag or hint field) always runs OCR. The reasons end up in
the trace.

```json
"ocr_regeln": {"min_schluesselwoerter": 2, "max_muell_anteil": 0.25,
               "nach_ki_meldung": true, "wenn_kein_typ": false}
```

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

Icon: <a href="https://www.flaticon.com/authors/magnific" target="_blank" rel="noopener">Origami PNG Image by Magnific - flaticon.com</a>
