---
type: Task
title: 'Panel title bar and navigation wrap on narrow screens'
status: erledigt
id: T-22
milestone: M-1
tags: [panel, ui]
created: '2026-11-19'
---
# T-22 — Panel title bar and navigation wrap on narrow screens

**Occasion (2026-11-19):** at a viewport width of 500 px the title bar with the navigation ran past the right edge on
every panel page (page width 855 px, horizontal scrolling). It was found while building the browser test of the info
page (T-21), which only measured the content area, not the shared frame.

**Cause:** the panel's own frame (`huelle.seite`), not the vendored C22 stylesheet. Title bar row and navigation were
plain flex containers without `flex-wrap`; five buttons plus logo and sign-out needed about 855 px and could not shrink.

**Fix:** `flex-wrap` on the title bar row and on the navigation, both canonical C22 classes (no own CSS). Narrow, the
navigation first drops below the logo and then wraps onto lines of its own; at desktop widths the bar stays on one line.

**Measured:** `tests/test_browser_breite.py` (new) renders every panel page in real Chrome with the vendored C22 stylesheet
at 500, 390 and 360 px and asserts `document.documentElement.scrollWidth <= innerWidth` and that every navigation item and
the sign-out button lie inside the window; at 1280 px it asserts the bar stays on one line. Widths below Chrome's headless
minimum window are measured in an iframe of that width. `tests/test_browser_info.py` now measures the whole page instead of
the content area only. Mutants (remove `flex-wrap` from the row, from the navigation, from both): red on all five pages.
