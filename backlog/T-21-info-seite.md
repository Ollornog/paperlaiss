---
type: Task
title: 'Info page in the panel: what paperlaiss does and how to use it'
status: erledigt
id: T-21
milestone: M-1
tags: [panel, doku]
created: '2026-11-19'
---
# T-21 — Info page in the panel: what paperlaiss does and how to use it

**Occasion (2026-11-19):** the panel had an `/info` page that said what paperlaiss is and named its building blocks, but
not how to use it or what it can do: the AI button, the export, routing, the ingest endpoint, fields only people set.

**Implementation:** `/info` is now the user guide, in the panel's language (German; the panel has no i18n). Sections:
what it does, how it is used, configuration, limits, building blocks. One source instead of a second upkeep: the
settings list is built from `EINSTELLUNGEN` (the same table as the *Settings* page, API keys excluded), and details link
to README sections whose anchors a test checks. README and its German mirror got the section *Fields and tags only people
set* and the missing `manual_fields` row.

**Measured:** `tests/test_panel_info.py` (structure, every settings key listed, anchors in both READMEs, route behind the
sign-in check, no third-party resource) and `tests/test_browser_info.py` (real Chrome, vendored C22). The browser test found
a real flaw during the build: a table inside a grid item widened the whole page on a phone (fixed with `min-w-0`).
