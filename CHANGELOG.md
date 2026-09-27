# Changelog

Alle nennenswerten Änderungen an diesem Projekt. Das Format folgt lose
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen
[Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt — Export-Knopf in Paperless (ein PDF oder einzeln, mit Inhaltsverzeichnis)

- Neuer Eintrag **„Export"** im Menü „Actions" der Mehrfachauswahl, neben „KI". Der Dialog bietet
  zwei Varianten:
  - **Ein PDF**: alle gewählten Dokumente zusammengefügt, ein Lesezeichen je Dokument (die
    Lesezeichen der Quelle darunter), optional **Seitenzahlen** („Seite i von n", auch auf gedrehten
    und beschnittenen Seiten) und ein **Inhaltsverzeichnis** vorn: Titel und „Seite n" springen zur
    ersten Seite des Dokuments, „In Paperless öffnen" führt zur Dokumentansicht.
  - **Einzeln**: jedes Dokument unverändert (byte-gleich mit dem Download aus Paperless) als eigene
    Datei; **Dateiname aus einer Vorlage** mit `{titel}` `{korrespondent}` `{typ}` `{datum}` `{jahr}`
    `{monat}` `{hinzugefuegt}` `{id}` `{asn}` `{seiten}` `{original}` und `{feld:Name}`; optional
    **durchnummeriert** (`001_`), als **ZIP** und mit **Inhaltsverzeichnis-PDF**. Dort verlinkt der
    Titel die Nachbardatei per Remote-Go-To (PDF-Betrachter) und „Datei: …" dieselbe per relativem
    URI (Browser) — je nach Betrachter greift das eine oder das andere; dazu der Paperless-Link.
  - Beide: **Sortierung** nach einer Variable oder einem Feld, auf- oder absteigend (Text natürlich:
    „9" vor „10", Ä wie A; ohne Wert hinten; bei Gleichstand die Reihenfolge der Auswahl).
- Quelle ist das Archiv-PDF, sonst das Original, wenn es ein PDF ist. Alles andere wird übersprungen
  und genannt — im Dialog und im Verzeichnis unter „Nicht enthalten", mit Grund.
- **Rechte wie beim KI-Knopf, aber Leserecht genügt**: `X-Paperlaiss: 1` ist Pflicht, das Panel
  fragt mit der Paperless-Sitzung, und ein nicht lesbares Dokument lehnt den ganzen Export ab (403),
  statt es still wegzulassen. Status und Download prüfen bei jedem Abruf erneut. Auch Namen
  (Korrespondent, Typ, Felder) kommen über die Sitzung des Nutzers; die PDFs lädt das Panel mit
  seinem Token.
- **Grenzen und Aufräumen**: `EXPORT_MAX_DOKUMENTE` (200), `EXPORT_MAX_MB` (200, Summe der PDFs,
  beim Herunterladen blockweise gemessen), `EXPORT_PARALLEL` (1), höchstens fünf offene Aufträge. Das
  Ergebnis bleibt `EXPORT_AUFBEWAHRUNG_MIN` (30) Minuten abrufbar, dann sind Auftrag und Dateien weg
  (Zeitgeber je Auftrag; beim Start werden Reste eines früheren Prozesses gelöscht). Ein Abbruch
  räumt sofort auf. Links nach Paperless über `PAPERLESS_PUBLIC_URL`, sonst die Adresse der
  aufrufenden Paperless-Seite (nur vom selben Ursprung); Uhrzeit in `PAPERLESS_TIME_ZONE` bzw. `TZ`.
- **Dateinamen entschärft**: keine Pfadtrenner, Steuer- und Formatzeichen (auch keine
  Richtungsumkehr U+202E), keine unter Windows verbotenen Zeichen oder Namen, kein Punkt am Rand,
  höchstens 150 Bytes; Kollisionen — ohne Rücksicht auf Groß-/Kleinschreibung — werden „ (2)", „ (3)".
- **Bibliotheken** (gepinnt, neueste stabile): `pypdf[crypto]` 6.19.0 (BSD-3-Clause) fügt zusammen,
  setzt Links, Lesezeichen und die Seitenzahl-Ebene; `[crypto]`, damit auch AES-geschützte PDFs mit
  bloßem Besitzerpasswort lesbar sind. `reportlab` 5.0.1 (BSD) zeichnet Verzeichnis und Seitenzahlen
  und misst Textbreiten fürs Kürzen. fpdf2 wäre leichter, steht aber unter LGPL-3.0; reportlab passt
  ohne Abwägung zur MIT-Lizenz. Schrift: DejaVu Sans (`fonts-dejavu-core` im Abbild), sonst
  Helvetica. Nichts wird vom Browser nachgeladen.
- Tests: `tests/test_export.py` (Logik, stdlib-only, dazu per AST: jeder Export-Endpunkt fragt die
  Sitzung — vor jeder Suche nach dem Auftrag —, Status und Download prüfen erneut, Start lehnt
  Unlesbares ab, der Download misst die Größe); `tests/abbild_export.py` prüft den PDF-Bau im gebauten Abbild (neuer Schritt im CI-Job
  `image`); `tests/test_panel_js.py` prüft jetzt auch das Knopf-Skript mit `node --check`. 24
  Mutationen — je Schutz einer abgeschaltet — alle rot. Auf dem Testbett im Browser belegt: beide
  Varianten samt Downloads (mit pypdf geprüft: Sprünge, Lesezeichen, Seitenzahlen, ZIP-Namen,
  Link-Ziele, byte-gleich mit dem API-Download), Dokumente danach unverändert; Rechte, Grenzen und
  Aufräumen aus dem Browser heraus.

### Geändert — KI-Antwort per JSON-Schema, Prompt-Caching, Anfang + Ende

- **Pass 1 und Pass 2 antworten nach JSON-Schema** (`response_format: json_schema`, strict) statt nur
  „irgendein JSON" (`json_object`): Dokumenttyp nur aus der Liste oder null, Felder, Absender-Daten
  und — bei Pass 2 — nur einer der Kandidaten. Zusatzschlüssel eigener Prompts bleiben erlaubt.
  Ein gültiges Schema garantiert den Aufbau, nicht die Richtigkeit der Werte.
- **Prompt-Caching** (`prompt_cache_key`, ein Schlüssel je System-Prompt): zwischengespeicherte
  Tokens kosten 10 %. Auf dem Testbett kamen ab dem zweiten Dokument 640–870 Token des Prompts aus
  dem Cache, beim OCR-Nachlauf 4034 von 7030. Die Nutzung je Aufruf steht im Trace (`ki_nutzung`).
- **Lange Dokumente: Anfang und Ende.** `content_max_len` (neu 10000) ist die Gesamtlänge, davon
  `content_end_len` (1000) vom Schluss — Summe und Fälligkeit stehen oft dort. Bisher gingen nur die
  ersten 7000 Zeichen an die KI. Stichprobe (13 Dokumente, darunter eines mit 38 800 Zeichen):
  Zuordnungen unverändert.

### Geändert — Gegenüber-Regel aufgeweicht, Bankdaten keine Kandidaten

- „correspondent ist nie die eigene Firma" war zu hart: Bei internen Dokumenten (Lohnabrechnung,
  Überweisungsliste) wich die KI auf die Bank aus, deren Bankverbindung darauf steht. Jetzt:
  Absender bei eingehenden, Empfänger bei eigenen Dokumenten an Kunden, die eigene Firma (unter dem
  ersten Namen aus `eigene_kennungen.namen`) nur bei internen Dokumenten ohne externes Gegenüber, eine
  Bank nur als Ausstellerin.
- Die Namenssuche überspringt Zeilen mit Bankdaten (IBAN, BIC, Bank, Konto) — bei kurzen Dokumenten
  lag die Fusszeile im Briefkopf-Fenster, und die Bank wurde zum einzigen Kandidaten.
- Stichprobe Testbett (13 Dokumente): interne Dokumente → eigene Firma, eigene Rechnungen/Verträge →
  Kunde, Lieferanten unverändert; ein Barverkauf ohne Kundennamen landet bei der eigenen Firma.

### Geändert — TinySesam 0.21.0

- Panel auf TinySesam **0.21.0** (Unterpfad-Montage T-15: Weiterleitungen, `next=` und Logout tragen
  `PANEL_PFAD`; belegt auf dem Testbett hinter einem abschneidenden Caddy). Beim Update beachten:
  `cryptography` kommt als Abhängigkeit mit; TinySesam legt `<PANEL_AUTH_DB>.key` neben der
  Benutzerdatenbank an — **mitsichern, getrennt von der Datenbank**; Sitzungen ohne „Angemeldet
  bleiben" enden nach 8 Stunden Leerlauf; neue Passwörter brauchen 15 Zeichen.

### Hinzugefügt — Panel unter einem Unterpfad (`PANEL_PFAD`)

- Das Panel läuft auch unter einem Pfad derselben Domain wie Paperless (etwa `/paperlaiss`), hinter
  einem Proxy, der den Präfix abschneidet. Jeder Link, jede Stil-/Skriptdatei und jeder API-Aufruf
  bekommt den Präfix (`huelle.u()`, `PL_BASIS` in `holen()`), uvicorn startet mit `--root-path`, und
  die Anmeldeseite zeigt das Logo unter dem Pfad. Passt `PANEL_BASE_URL` nicht zum Pfad, startet der
  Container nicht. Belegt auf dem Testbett hinter einem abschneidenden Caddy; die Weiterleitungen
  von TinySesam brauchen dafür 0.21.0 (Unterpfad-Montage, T-15).
- Mit `PANEL_OIDC_GROUPS` fordert das Panel den Scope `groups` an. Ohne ihn schickt PocketID keine
  Gruppen, und die Gruppensperre wiese jeden ab — auch den Admin (TinySesam gemeldet).

### Geändert — Kandidaten ohne Pass 0, Stammdaten nachtragen, eigene Firma

- **Pass 0 entfällt.** Statt eines eigenen KI-Aufrufs, der nur einen Absendernamen riet, sucht
  paperlaiss im Text nach den Stammdaten *aller* Korrespondenten (USt-ID, IBAN, Mail, Domain,
  Kundennummer) und im Briefkopf nach ihren Namen und Aliasen; die Absender-Mail zählt mit. Alles geht
  mit Fundstelle als Kandidat an Pass 1. Stichprobe auf dem Testbett (16 Dokumente gegen den Stand in
  Paperless): gleich viele Treffer wie mit Pass 0 (10), ein KI-Aufruf weniger.
- Die Absender-Mail ist ein **Kandidat, keine Zuordnung** — ein Portal verschickt Dokumente vieler
  Firmen von einer Adresse. Mail-Abgleich über volle Adresse, dann Domain (auch Subdomain, nie
  Freemail); mehrdeutig heißt „keine Aussage“. Bisher reichte ein Teilstring.
- **Stammdaten nachtragen** (`stammdaten_erfassen`, Vorgabe an): Pass 1 liefert die Kontaktdaten des
  Gegenübers (`absender`), paperlaiss schreibt sie nach der Zuordnung nur in **leere** Felder von
  `correspondents.json`, mit Herkunft (`erfasst`), die der Paperless-Dialog zeigt. Formate werden
  geprüft, die Absender-Mail nur bei nachweislicher Zugehörigkeit übernommen. Neues Feld **IBAN**.
  Panel und Klassifizierer schreiben unter derselben Dateisperre (`correspondents.json.lock`).
- **Eigene Firma** (`eigene_kennungen`: Namen, USt-IDs, IBANs, Mail-Domains und -Adressen): zählt nie
  als Absender, wird nie nachgetragen, ist bei der Namenssuche kein Kandidat, und Pass 1 erfährt, wer
  „wir“ sind — gesucht ist immer das Gegenüber.
- Ablauf und Lauf-Popup zeigen die neue Suche und das Nachtragen; ältere Läufe mit Pass 0 werden
  weiter angezeigt.

### Geändert — Panel auf Python 3.14, Ablauf mit Textvorschau

- Panel-Abbild auf `python:3.14-slim` (vorher 3.12; der Dependabot-PR dazu hatte sich selbst
  geschlossen). Auf dem Testbett gebaut und gestartet, alle Seiten laden.
- Ablauf und Lauf-Popup: Eingabe und Ausgabe zeigen immer die ersten drei Zeilen; ist mehr Text
  da, blendet er nach unten aus, und „… mehr anzeigen" klappt ihn auf. Passt alles, gibt es weder
  Ausblenden noch Knopf. Sonderweg per Inline-Maske, weil C22 kein line-clamp hat (C22 T-9).
- Auslöser und Ende größer (Chip, Symbol, Schrift).
- Lauf-Popup: die Ausgabe von „Nach Paperless geschrieben" ist aufgeklappt; die
  Korrespondenten-Zuordnung steht als Text im Kasten statt als Chip.
- Backlog T-4 („Erneut verarbeiten" gegen „KI") verworfen: bleibt so (PO-Entscheidung).

### Geändert — Korrespondent zuordnen (Pass 2) in derselben KI-Unterhaltung wie Pass 1

- Pass 2 ist kein eigener Aufruf mit nur dem Namen mehr, sondern eine weitere Nachricht in der
  Pass-1-Unterhaltung: die KI sieht dabei das ganze Dokument und ihre eigene Analyse
  (`pass2_frage()`). Die Schnittstelle hat kein Gedächtnis — der Verlauf wird mitgeschickt, wie
  schon beim OCR-Nachlauf und der Selbstkorrektur. Test belegt die Verdrahtung (Mutation rot).
- Ablauf: Regeln als Tabelle „Wenn → Dann" in normaler Schrift, der aktuelle Stand der
  Einstellungen getrennt darunter (vorher Plaketten mit gemischtem Text).
- Aktivität: „Info" hieß in Wahrheit „Trockenlauf" (DRY, nichts geschrieben) — jetzt so
  benannt; sonstige unbekannte Zeilen heißen „Hinweis".
- Aktivität: fünf Kennzahlen wieder in einer Reihe; Verlauf über die volle Breite mit 60 Tagen als
  flache Balkenreihe (das C22-Diagramm hat ein festes Seitenverhältnis — Sonderweg, in C22 gemeldet);
  Symbole je Ereignisart.
- Lauf-Popup scrollt (der Dialoginhalt war abgeschnitten).
- Ablauf: Schritt „Mistral-OCR · Text neu lesen" mit seinen Bedingungen statt „Text brauchbar?";
  Symbole je Schrittart, größere Überschriften und Pfeile.
- Lauf-Popup: nur noch die Schritte, die in diesem Lauf passiert sind (kein OCR-Schritt ohne OCR).
- Ablauf und Lauf-Popup: Symbole getrennt neben den Chips und größer, noch größere Pfeile mit
  mehr Abstand zu den Kästen, mehr Luft zwischen Kopf und Inhalt; im Popup werden die
  Kastenränder nicht mehr abgeschnitten. Die Schritt-Kästen heben sich mit eigener Fläche und
  Schatten vom Hintergrund ab; der Chip nennt, wer den Schritt ausführt („paperlaiss" statt
  „Schritt").
- Ablauf und Lauf-Popup: ein Schritt ist jetzt ein nummerierter Container um alles, was zu ihm
  gehört (Vorbereiten · Text beschaffen · Absender erkennen · Analysieren · Korrespondent
  zuordnen · Schreiben), darin die Teilschritte mit kleinen Pfeilen. Oben stehen die Auslöser je
  mit Symbol (im Popup der eine, der den Lauf gestartet hat), unten „Ende" mit Haken bzw.
  „Abgebrochen" mit Kreuz — beide mit Abstand zum Rand.
- Panel: kleinere Schrift überall. Ablauf: jeder Block sagt in einem Satz, was er tut („OCR — Text
  neu erkennen" statt „Text neu lesen"); Eingabe und Ausgabe als abgesetzte Kästen mit farbigem
  Etikett statt schlichter Aufklapp-Zeilen.
- Pass 1: ein Feld statt zwei für den System-Prompt — die Anweisung, wie sie an die KI geht, mit
  hinterlegten eingesetzten Werten; „Bearbeiten" öffnet die Vorlage darüber, und jede Änderung
  rechnet die Vorschau live neu (`POST /api/prompt-vorschau` mit dem Entwurf, speichert nichts).
  Unverändert gespeichert heißt: eingebauter Prompt, keine Kopie.
- Die Nachrichten an Pass 0, Pass 1 und Pass 2 zeigt der Ablauf jetzt im echten Wortlaut, mit
  Beispielwerten und — bei Pass 1 — der Bedingung je Block. System-Prompt und Pass-1-Nachricht
  entstehen dafür in `classify.py` aus Stücken (`baue_system_teile`, `pass1_system_teile`,
  `pass1_nachricht_teile`, `pass0_nachricht`); der Lauf fügt sie zusammen, ein Test vergleicht
  Zeichen für Zeichen mit der bisherigen Nachricht (Mutation rot).
- Pass 1: Die Kandidatenliste ist ein Angebot, keine Pflicht. Bisher hieß es „wähle GENAU einen
  dieser Namen; nur wenn wirklich keiner passt einen neuen" — das drängte die KI zur Liste, und ein
  ähnlicher, aber falscher Name wurde exakt übernommen und direkt zugeordnet (Pass 2 prüft nur
  Namen, die nicht exakt passen). Jetzt: passt einer, seinen Namen exakt übernehmen; sonst den
  tatsächlichen Absender nennen.
- Panel: eine Spur für alle Seiten (die innere, schmalere entfällt).
- Panel: „Nachbearbeitung" heißt jetzt „Eigenes Skript danach (optional)" — sie ist nicht die
  Selbstkorrektur bei abgelehnten Werten, die gehört zum Schreiben. Mehr Luft um den Seitentitel.

### Hinzugefügt — Stammdaten der Korrespondenten im Paperless-Dialog

- Das Knopf-Skript blendet im Bearbeiten-Dialog eines Korrespondenten den Abschnitt *paperlaiss*
  ein: Kontext für die KI, Aliase, E-Mail, Mail-Domains, Kundennummer, USt-ID, Telefon, Adresse.
  Gespeichert mit Paperless' *Save* über `GET/POST /knopf/korrespondent/{id}`; berechtigt ist, wer
  den Korrespondenten in Paperless ändern darf. Import-Felder (`quelle`, `extern_id`) bleiben
  beim Speichern erhalten (`kern.korr_eintrag()`).
- Panel: der Seitenkopf mit den Aktionen (etwa „Speichern") bleibt beim Scrollen stehen.

### Geändert — ein Knopf „KI", Ablauf als Schrittliste mit Eingabe und Ausgabe

- Der OCR-Knopf und der Nur-OCR-Modus (`CLASSIFY_NUR_OCR`) entfallen — der KI-Knopf liest ohnehin
  immer per Mistral-OCR neu. Der Knopf heißt nur noch „KI", auch im Menü „Actions".
- **Ablauf & Prompt** und der **Lauf** in der Aktivität nutzen dieselbe Schrittdarstellung: Nummer,
  Art, Regeln „wenn … → …", aufklappbar Eingabe und Ausgabe — bei KI-Aufrufen Prompt und Antwort.
  Keine Rauten mehr. Der Prompt von Pass 1 ist im Ablauf direkt bearbeitbar.
- Pass 0 legt Prompt und Antwort jetzt im Trace ab; die kleinen Prompts von Pass 0/2 sind
  Konstanten (`PASS0_SYSTEM`, `PASS2_SYSTEM`) und erscheinen in der Vorschau.
- Panel: Titelleiste und Inhalt in einer begrenzten Spur; neue Seite **Info** mit GitHub-Link.

### Geändert — Knöpfe rufen paperlaiss direkt; Tag-Auslöser entfernt

- KI-/OCR-Knopf rufen das Panel direkt (`POST /knopf`, Status `GET /knopf/status`). Berechtigt
  ist, wer das Dokument in Paperless ändern darf — geprüft mit der Paperless-Sitzung des Nutzers
  (`user_can_change`, Logik `kern.knopf_rechte()`). Kein Tag, kein Hinweisfeld, kein Workflow mehr.
- **Entfernt:** Webhook `/redo`, `REDO_SECRET`, `deploy/neu-klassifizieren-einrichten.py`, die
  Config-Schlüssel `redo_tag`, `ocr_tag`, `hinweis_field`. Neu: `PAPERLAISS_URL` (Paperless-Container),
  `PAPERLAISS_KNOPF_ORIGIN` (Panel, nur bei getrennten Adressen).
- In der Mehrfachauswahl stehen KI und OCR jetzt im Menü **Actions** statt als eigene Knöpfe.

### Geändert — Panel: Navigation in der Titelleiste, Ablauf als Flussdiagramm, Einstellungen erklärt

- Keine Seitenleiste mehr; die drei Seiten stehen in der Titelleiste.
- **Ablauf & Prompt** nach den üblichen Flussdiagramm-Regeln: Oval Start/Ende, Raute Entscheidung
  mit beschrifteten Zweigen, Paperless-Schritte hinterlegt, KI-Knoten mit Eingabe → Modell →
  Ausgabe; Legende oben.
- **Einstellungen** in Gruppen, jede mit Titel und Beschreibung (`seiten.EINSTELLUNGEN`); ein Test
  stellt sicher, dass jeder Schlüssel des Klassifizierers eine hat. Der Klassifizierer gibt nur noch
  Schlüssel aus, die er kennt — veraltete Reste einer alten Datei erscheinen nicht mehr.

### Geändert — Panel neu auf C22: Aktivität mit Filtern, Lauf als Entscheidungsbaum, Ablauf-Editor

- **Aussehen aus C22** (vendort unter `panel/static/c22/`, `scripts/vendor-c22.sh`, mit Herkunft
  und dem OFL-Lizenztext der Schrift Inter). Gleiche Navigation auf jeder Seite, die aktive
  hinterlegt. Wächter `tests/test_c22_klassen.py`: jede Klasse und Variante muss im Pack stehen.
- **Aktivität:** Kennzahlen und Verlauf filtern die Liste (Filter in der Adresse, Zurück hebt ihn
  auf), 100 Einträge je Seite (`/api/aktivitaet`, Logik `kern.aktivitaet()`); eine Zeile öffnet den
  Lauf mit Entscheidungsbaum, Prompt, Ausgabe und OCR-Text als Markdown.
- **Ablauf & Prompt:** Entscheidungsbaum mit großen Pfeilen; ein Klick auf einen Knoten bearbeitet
  seine Einstellungen, auch den Prompt.
- **Einstellungen/Config:** das Panel zeigt die wirksame Config (Datei + Vorgaben,
  `CLASSIFY_DUMP_CONFIG=1`) und schreibt beim Speichern nur geänderte Schlüssel.
- **Entfernt:** Korrespondenten-Seite samt Zusammenführen (Stammdaten gehören nach Paperless bzw.
  ins eigene System), `/api/stats`, `/api/feed`, `/api/correspondents*`; `/trace/{id}` leitet in
  die Aktivität um.

### Behoben — Läufe mit OCR fehlten bei „klassifiziert"

- `log_art()` suchte Teiltexte der Reihe nach; die Erfolgszeile eines Laufs mit OCR
  („OK 913 | … | OCR-rescue(340)") traf zuerst „OCR-rescue". Jetzt entscheidet das erste Wort.
- Die OCR-Schlüsselwörter verloren in PR #58 ihre Leerzeichen (`' der '` → `der`, traf dann auch
  „oder"); wieder wörtlich.

### Geändert — Knöpfe auch in der Mehrfachauswahl, „Suggest" ausgeblendet

- KI/OCR stehen jetzt auch in der Leiste der Mehrfachauswahl und gelten für alle markierten
  (sichtbaren) Dokumente — über Paperless' Sammelbearbeitung, ein Workflow-Lauf je Dokument.
  Mit Hinweis wird nur das Hinweisfeld gesetzt, damit nicht zwei Läufe je Dokument entstehen.
- Paperless' eigenes „Suggest" ist in der Dokumentansicht ausgeblendet.
- Das Panel fährt Läufe aus Paperless höchstens `PANEL_PARALLEL` (Vorgabe 2) gleichzeitig.

### Hinzugefügt — KI- und OCR-Knopf in Paperless (ohne Fork)

- `deploy/paperless-knoepfe/`: Init-Skript für `/custom-cont-init.d` + Browser-Skript. **KI**
  (optionaler Hinweis → neu klassifizieren mit OCR), **OCR** (nur Text neu lesen). Die Knöpfe
  nutzen nur die Paperless-API mit der Sitzung des Nutzers; ausgelöst wird über den vorhandenen
  Workflow. Fertig-Signal: der Lauf setzt den Marker-Tag wieder bzw. entfernt den OCR-Tag erst
  mit dem Text — danach lädt die Seite neu.
- **Nur-OCR-Modus** (`CLASSIFY_NUR_OCR=1`, Auslöser-Tag `ocr_tag`), Einrichtungsskript legt Tag
  und dritten Workflow-Auslöser an.
- **Beim ausdrücklichen Neu-Klassifizieren** (Knopf, Panel) darf die KI einen vorhandenen
  Dokumenttyp ändern; automatisch weiterhin nur einen leeren setzen (`typ_setzen()`).

### Hinzugefügt — Ablauf & Prompt im Panel (`/ablauf`)

- Jeder Schritt eines Laufs mit den aktuellen Einstellungen (Auslöser, Schleifenschutz, OCR-Regeln,
  Pass 0/1, OCR-Nachlauf, Schreiben, Nachbearbeitung) und darunter der **System-Prompt von Pass 1,
  wie er gesendet wird**. Gebaut wird er von `classify.py` selbst (`CLASSIFY_PROMPT_VORSCHAU=1`,
  gemeinsame Funktion `pass1_system()`); ein Test belegt, dass Vorschau und gesendeter Prompt
  Zeichen für Zeichen gleich sind.

### Geändert — Neu klassifizieren schreibt direkt, immer mit OCR; Vorschlagsmodus entfernt

- **Auslöser aus Paperless** (Tag bzw. Hinweisfeld) klassifiziert neu, **immer mit Mistral-OCR**,
  und schreibt direkt. Der Lauf startet im Hintergrund (`/redo` antwortet 202), weil er mit OCR
  länger dauert, als Paperless auf einen Webhook wartet.
- **Vorschlagsmodus entfernt** (`CLASSIFY_PROPOSE`, Ablage `proposals/`, Annehmen/Verwerfen im
  Panel). paperlaiss ist Middleware; entschieden wird in Paperless.
- `deploy/vorschlagsmodus-einrichten.py` heißt jetzt `deploy/neu-klassifizieren-einrichten.py`.

### Hinzugefügt — OCR-Fallback mit Regeln und KI-Meldung (`ocr_regeln`)

- **Vor Pass 1:** einstellbare Regeln statt fest verdrahteter Heuristik, neu mit Zeichensalat-Anteil.
  Die Gründe stehen im Trace. Am Testbett (632 Dokumente) greifen die Regeln bei 33, Zeichensalat
  bei keinem sauberen Dokument.
- **Nach Pass 1:** meldet die KI unlesbaren Text (oder, wenn eingeschaltet, fehlt Typ bzw.
  Korrespondent), wird per OCR neu gelesen und erneut analysiert. Dieser Zweig war seit dem
  Aufräumen am 2026-09-21 nur noch eine Meldung — der alte Code dazu war unerreichbar. Ein Test
  lässt `main()` jetzt gegen gefälschte Aufrufe laufen und belegt die Verdrahtung.

### Hinzugefügt — Anmeldeseite für das Panel (TinySesam)

- **`PANEL_AUTH=tinysesam`:** eigene Anmeldeseite statt nur Bearer-Token. OIDC (PocketID) über
  `PANEL_OIDC_*`, Benutzername + Passwort nur mit `PANEL_PASSWORD_LOGIN=1` (Testsystem), keine
  Selbstregistrierung. Fehlkonfiguration (kein Anmeldeweg, halbe OIDC-Angaben, Admin-Konto ohne
  Passwort-Login) beendet den Start mit einer Meldung, statt offen oder unbenutzbar zu laufen.
  Abmelde-Link in jeder Panel-Seite; `PANEL_TOKEN` bleibt für Skripte gültig. Neue Abhängigkeit
  des Panels: `tinysesam[oidc,argon2]==0.20.1`.
- **Projektbild im Panel:** groß über der Anmeldeseite (mit Bildnachweis), klein in jedem
  Seitenkopf, als Favicon. Die Datei liegt jetzt unter `panel/paperlaiss.png` (vorher `docs/`),
  weil nur `panel/` ins Abbild gebaut wird — eine Quelle statt einer Kopie.

### Behoben — Bestandsprompts verloren still Tags und Zusammenfassung

Aufgefallen beim Umstieg einer Installation vom älteren Stand auf den Repo-Stand: der Lauf sah
normal aus, vergab aber keinen einzigen Tag und ließ das Zusammenfassungsfeld leer.

- **Platzhalter `{TAGS}` wird wieder ersetzt.** Der Code kannte nur noch `{TAGBLOCK}`; ein
  `system_prompt` mit dem älteren `{TAGS}` bekam keine Tag-Liste. Neu: `{TAGS}` erhält die reine
  Liste, `{TAGBLOCK}` den ganzen Block, und bei aktivem Tagging ohne beide Platzhalter wird der
  Block angehängt statt verschluckt (`baue_system()`).
- **Zusammenfassung auch aus `summary_long`/`summary_short`.** Ältere Prompts verlangen diese
  Schlüssel, und das Modell hält sich daran (`summary_aus()`).

### Geändert — Python-Untergrenze bewusst an die neueste stable Reihe gebunden (T-3)

- `requires-python` folgt weiter der Testmatrix (die drei neuesten stable Reihen) — jetzt als
  Entscheidung festgehalten statt als Nebenwirkung einer Kit-Prüfung. Mit Python 3.15 steigt die
  Untergrenze auf 3.13. Gemessen läuft `classify.py` auch unter 3.8; zugesagt wird das nicht.

### Behoben — Build-Kontext ohne `.dockerignore`

- **`panel/.dockerignore` neu.** Gebaut wird aus `./panel`, eine Ignore-Liste gab es dort nicht —
  folgenlos nur, weil das Dockerfile jede Datei gezielt kopiert. Neuer Test: jeder Build-Kontext aus
  den Workflows hat seine `.dockerignore` (mit `.env` und `**/__pycache__`), und keine liegt
  außerhalb eines Kontexts, wo sie nie griffe.

### Geändert — Testbasis auf Kit 0.16.2 (Gleichstand)

`repokit sync` verteilte bisher den **Arbeitsbaum** des Kit-Klons statt des freigegebenen
Standes auf dessen Default-Branch. Dieses Repo bekam dadurch ein `tests/_kit` mit der
Aufschrift 0.16.1, das zu dem Zeitpunkt noch nicht beschlossen war — der Inhalt war nicht
falsch, aber er war nie freigegeben. Welcher Stand ein Repo abbekam, hing allein daran, was
im Kit-Klon gerade ausgecheckt war.

Kit 0.16.2 behebt die Ursache: die Quelle wird aus `origin/<default-branch>` materialisiert
und für den ganzen Lauf festgehalten. Dieser Commit ist die Gegenprobe dazu — ein
gewöhnlicher `repokit sync .` liefert jetzt 0.16.2, ohne Kunstgriff. An den verteilten
Dateien ändert sich nichts außer der Versionsangabe: der Fehler saß im Werkzeug, nicht im
Kit-Inhalt.

### Geändert — Dependabot bündelt Patch und Minor, Auto-Merge ist aus

Jeder `updates:`-Block in `.github/dependabot.yml` hat jetzt eine Gruppe `klein`, die
**patch und minor** in EINEN PR zusammenfasst. Majors bleiben absichtlich draußen und kommen
einzeln.

Anlass ist eine Entscheidung mit Vorgeschichte: Auto-Merge war repo-weit aktiv und hat
Dependabot-PRs **selbst gemergt** — Tage nach dem Aktivieren und nach einem Rebase, den
niemand angesehen hat. Der Schalter `allow_auto_merge` ist deshalb aus, gemergt wird von
Hand. Die Bündelung ist die Gegenleistung dafür, dass „von Hand" nicht „mehr Arbeit" heißt:
ein Patch-Bump mit gepinntem SHA und grüner Suite braucht keinen eigenen PR, ein Major
schon — der kann die Laufzeit wechseln (node20 → node24) oder Eingaben entfernen.

Bei pip ersetzt `klein` die bisherige Gruppe `alle` (`patterns: ["*"]` ohne Filter). Zwei
Gruppen mit demselben Muster im selben Block überschneiden sich, und Dependabot verlangt
eindeutige, nicht überlappende Gruppen — also umbauen statt daneben setzen.

### Geändert — Testbasis auf Kit 0.16.1

`repokit sync` zieht drei Korrekturen nach:

- **oktal escapte Umlaute in `git ls-tree`**: eine vorhandene Datei mit Umlaut im Namen galt
  der Dateilisten-Prüfung als fehlend.
- **eine Subdomain namens `www` ist keine interne Dienst-Subdomain** mehr: das Muster traf
  vorher jede Quellenangabe dieser Form. Der Anker sitzt jetzt am Anfang des Hostnamens,
  damit ein Dienstname vor dem `www` nicht durchschlüpft.
- **generierte Dateien** (Lock-Dateien, IDE-Helfer) sind von den **Adress**prüfungen
  ausgenommen — ausdrücklich **nicht** von der Geheimnis-Prüfung.

### Sicherheit — jeder `actions/checkout` gibt das git-Token nicht mehr weiter

Alle Checkout-Schritte in `ci.yml` und `release.yml` setzen `persist-credentials: false`.
Ohne das legt checkout das Token so ab, dass **jeder spätere Schritt im selben Job** es lesen
kann — und nach dem Checkout läuft fremder Code (Build-Skript, Action eines Dritten). Seit
checkout@v6 liegt es in `$RUNNER_TEMP` statt in `.git/config`, damit ist es kleiner geworden,
aber nicht weg.

Kein Job hier braucht das Token: der Release veröffentlicht über `gh release create` und
`docker/login-action`, beide mit eigenem Token aus der Umgebung. Es gibt daher **keine
Ausnahme**. Das ist eigene Härtung, kein belegter Standard — GitHub empfiehlt es nirgends
ausdrücklich.

### Geändert — Testbasis auf Kit 0.14.0, drei neue Wächter scharf

`repokit sync` zieht drei Prüfungen nach, die ab jetzt auch gerufen werden:

- **Dateiliste vollständig**: eine leere oder lückenhafte Dateiliste macht jede folgende
  Hygiene-Prüfung grün, ohne dass sie etwas angesehen hat. Wird gegen `git ls-tree -r HEAD`
  gezählt.
- **`persist-credentials: false`** an jedem Checkout (siehe oben) — mechanisch statt auf Zuruf.
- **keine blanken fremden Hostnamen**: die bisherige Adressprüfung sucht nur URLs *mit*
  Schema, das Infrastruktur-Muster verlangt drei Namensteile. Eine blanke Second-Level-Domain
  fiel durch beide. Der Grundstock (`python.org`, `devguide.python.org`, `flaticon.com`,
  `ghcr.io`) ist durchgesehen und freigegeben; jede **neue** Adresse wird ab jetzt rot.

### Geändert — Python 3.12 ist die neue Untergrenze (Matrix 3.12 / 3.13 / 3.14)

`requires-python` steigt von `>=3.10` auf `>=3.12`, die CI fährt **3.12, 3.13, 3.14** statt
3.10 / 3.12 / 3.13.

Dahinter steht keine Zahl, sondern ein Fenster: **die letzten drei stable Minors**. Python 3.10
geht am 31.10.2026 EOL — eine Version, die niemand mehr fährt, ist eine Zusage ohne Deckung.
Die Obergrenze bleibt bewusst bei 3.14: 3.15 erscheint am 01.10.2026, kommt aber erst ins Gate,
wenn sie auch wirklich gelaufen ist.

Geführt wird die Matrix jetzt an **einer** Stelle (`repokit`, `tests/_kit/python_matrix.json`);
das CI-Abbild `ci-python-web` trägt dieselben drei Interpreter.

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
