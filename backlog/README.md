# Backlog

<!-- GENERIERT von scripts/_backlog.py — nicht von Hand pflegen. Neu bauen: `python3 scripts/_backlog.py index` -->

Die Wahrheit sind die Einzeldateien in diesem Verzeichnis; diese Seite ist ihr Abzug.
Konventionen: [README-KONVENTION.md](README-KONVENTION.md).

## Meilensteine

* ☐ **[M-1](M-1-produktionsreif.md)** Produktionsreif für fremde Installationen — 19/31 erledigt

## Aufgaben

* ☑ **[T-1](T-1-panel-bloecke-portieren.md)** Vier Panel-Blöcke aus der Flask-Fassung übernehmen · M-1
* ☑ **[T-2](T-2-eine-linie-statt-vier-staende.md)** Alle Installationen auf den Repo-Stand bringen · M-1
* ☑ **[T-3](T-3-python-untergrenze-bewusst-setzen.md)** Python-Untergrenze bewusst setzen statt von der Testmatrix schieben lassen · M-1
* ✗ **[T-4](T-4-erneut-verarbeiten-gegen-ki.md)** Paperless' „Erneut verarbeiten" überschreibt den OCR-Text des KI-Knopfs · M-1
* ☐ **[T-5](T-5-automatischer-export.md)** Automatischer Export nach Regeln (Filter, Turnus, Auslöser) · M-1
* ☑ **[T-6](T-6-korrektur-log-was-menschen-nach-der-ki-geandert-ha.md)** Korrektur-Log: was Menschen nach der KI geändert haben · M-1
* ☐ **[T-7](T-7-sammelscans-automatisch-teilen.md)** Sammelscans automatisch teilen · M-1
* ☑ **[T-8](T-8-ausrichtung-je-dokument-korrigieren-kopfuber-schra.md)** Ausrichtung je Dokument korrigieren: kopfüber, Schräglage, Ecken · M-1
* ☑ **[T-9](T-9-lehren-aus-einer-grosen-nacharbeit-fehlalarme-stam.md)** Lehren aus einer großen Nacharbeit: Fehlalarme, Stammdaten, Korrespondent · M-1
* ☑ **[T-10](T-10-kaputte-scans-uberlast-alias-und-kontrolllauf.md)** Kaputte Scans, Überlast, Alias-Treffer und ein Kontrolllauf · M-1
* ☑ **[T-11](T-11-feldfilter-tag-ausschluss-dubletten-und-stammdaten.md)** Feldfilter, Tag-Ausschluss, Dubletten und Stammdaten aus einer zweiten Durchsicht · M-1
* ☑ **[T-12](T-12-zweitscans-abrechnungsmonate-wahrung-und-fremde-personen.md)** Zweitscans, Abrechnungsmonate, Währung und fremde Personen aus einer dritten Durchsicht · M-1
* ☑ **[T-13](T-13-duplex-ruckseiten-papierscans-sammelmappen-und-namen.md)** Duplex-Rückseiten, Papierscans digitaler Originale, Sammelmappen und Namensvarianten aus einer vierten Durchsicht · M-1
* ☑ **[T-14](T-14-lohnabrechnungs-datum-im-code-und-ust-id-aus-dem-text.md)** Lohnabrechnungs-Datum im Code statt durch die KI, USt-ID nur aus dem Text · M-1
* ☑ **[T-15](T-15-allerweltsnamen-trace-marke-stammdaten-knopf-und-eingang-mit-archiv.md)** Allerweltsnamen, Marke im Trace, Stammdaten-Knopf und Eingang mit Archiv · M-1
* ☑ **[T-16](T-16-garantie-in-jahren-ende-aus-dem-code.md)** Garantie in Jahren, Ende aus dem Code · M-1
* ☑ **[T-17](T-17-titel-bruchstuck-und-spiegelbildliche-dubletten.md)** Titel-Bruchstück und spiegelbildliche Dokumente als Dublette · M-1
* ☑ **[T-18](T-18-neue-stammdaten-ohne-besitzer.md)** Neue Stammdaten ohne Besitzer, auch unter einem Dienstkonto · M-1
* ☑ **[T-19](T-19-ocr-nur-fuer-scans-und-freigabe-an-den-hub.md)** OCR nur für Scans und Fotos, Freigabe an den Hub ohne Tag · M-1
* ☑ **[T-20](T-20-reserved-fields.md)** Reserved custom fields the classifier never sets, changes or clears · M-1
* ☑ **[T-21](T-21-info-seite.md)** Info page in the panel: what paperlaiss does and how to use it · M-1
* ☑ **[T-22](T-22-panel-title-bar-wraps-on-narrow-screens.md)** Panel title bar and navigation wrap on narrow screens · M-1
* ☐ **[T-23](T-23-formulare-mit-groesserem-modell-messen.md)** Formulare mit einem größeren Modell gegen die Sollliste messen · M-1
* ☐ **[T-24](T-24-begradigen-je-dokument-und-vier-ecken.md)** Begradigen je Dokument abschalten oder Winkel setzen, vier Ecken entzerren · M-1
* ☐ **[T-25](T-25-detect-duplicates-between-a-digital-original-and-a.md)** Detect duplicates between a digital original and a scan · M-1
* ☐ **[T-26](T-26-capture-bank-statements-and-match-them-against-inv.md)** Capture bank statements and match them against invoices · M-1
* ☐ **[T-27](T-27-folder-import-in-the-panel-with-content-matching-a.md)** Folder import in the panel with content matching against the stock · M-1
* ☐ **[T-28](T-28-watcher-for-hanging-paperless-requests.md)** Watcher for hanging Paperless requests · M-1
* ☐ **[T-29](T-29-empty-pages-in-the-existing-stock.md)** Empty pages in the existing stock · M-1
* ☐ **[T-30](T-30-pass-2-assign-correspondent-inside-the-pass-1-conv.md)** Pass 2 (assign correspondent) inside the pass 1 conversation · M-1
* ☐ **[T-31](T-31-measure-quality-against-paperless-built-in-classif.md)** Measure quality against Paperless' built-in classifier · M-1

## Entscheidungen (ADR)

* ☑ **[ADR-1](ADR-1-grounding-statt-freier-generierung.md)** Grounding gegen den Bestand statt freier Generierung
* ☑ **[ADR-2](ADR-2-eigener-klassifizierer.md)** Eigener Klassifizierer statt vorhandener Erweiterung
* ☑ **[ADR-3](ADR-3-naht-statt-fork.md)** Installationseigene Schritte über eine Naht statt über Forks
* ☑ **[ADR-4](ADR-4-ausrichtung-ueber-paperless-fassungen.md)** Ausrichtung beim Import per Vorab-Schritt, von Hand über die Fassungen von Paperless
