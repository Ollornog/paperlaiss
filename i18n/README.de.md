<p align="center"><img src="../panel/paperlaiss.png" alt="paperlaiss" width="250" height="250"></p>

<h1 align="center">paperlaiss</h1>

<p align="center"><a href="../README.md">English</a> · <b>Deutsch</b></p>

<p align="right">
<a href="https://github.com/Ollornog/paperlaiss/actions/workflows/ci.yml"><img src="https://github.com/Ollornog/paperlaiss/actions/workflows/ci.yml/badge.svg" alt="tests"></a>
<a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-informational.svg" alt="License: MIT"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python">
</p>

> 🚧 **In Arbeit** — wird aktiv entwickelt; Schnittstellen und Struktur können sich vor einem stabilen `1.0`-Release noch ändern.

### Ein grounded Dokumenten-Klassifizierer für Paperless-ngx.

Ein schlanker, eigenständiger Ersatz für [paperless-ai](https://github.com/clusterzx/paperless-ai).
Läuft als `POST_CONSUME_SCRIPT` (oder manuell / per Panel) und schreibt Metadaten direkt über die
Paperless-REST-API zurück.

Der Klassifizierer ist **stdlib-only** — keine Pakete zu installieren — und **mandantenunabhängig**:
jedes Feld und jeder Tag wird per *Name* gegen die API aufgelöst, jedes Verhalten ist ein Schalter
in der Config. Ein optionales FastAPI-Panel bringt eine Admin-Ansicht und einen Ingest-Endpunkt dazu.

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
   Unterstützt werden die drei neuesten stable Python-Reihen (derzeit 3.12–3.14); die
   Untergrenze steigt mit jeder neuen Python-Reihe mit, und zwar bewusst.

## Manuell und testen

```bash
CLASSIFY_DRY=1  CLASSIFY_DOC=<id>  python3 classify.py     # nur ausgeben, nichts schreiben
CLASSIFY_FORCE=1 CLASSIFY_DOC=<id> python3 classify.py     # schon klassifiziertes Dokument neu machen
CLASSIFY_FORCE_OCR=1 CLASSIFY_DOC=<id> python3 classify.py # Mistral-OCR erzwingen
```

## Panel

Ein Admin-Panel für den Fall, dass etwas hängt oder eingestellt werden muss — paperlaiss ist
Middleware, Stammdaten (Tags, Korrespondenten) bleiben in Paperless bzw. im eigenen System. Ein
FastAPI-Container im selben Docker-Netz, der sich das `scripts/`-Volume teilt. Das Aussehen kommt
aus dem Design-System [C22](https://github.com/Ollornog/C22), vendort unter `panel/static/c22/`
(`scripts/vendor-c22.sh`); `tests/test_c22_klassen.py` prüft jede Klasse dagegen.

- **Aktivität** (`/`) — fünf Kennzahlen und ein 30-Tage-Verlauf **filtern** die Liste (der Filter
  steht in der Adresse, *Zurück* hebt ihn auf), 100 Einträge je Seite. Eine Zeile öffnet den
  **Lauf**: Entscheidungsbaum, Prompt, Ausgabe der KI und den OCR-Text als Markdown.
- **Ablauf & Prompt** (`/ablauf`) — jeder Schritt, den ein Dokument durchläuft, aufklappbar mit Eingabe
  und Ausgabe; bei den KI-Aufrufen Prompt und Antwortformat. Der Prompt von Pass 1 ist dort
  bearbeitbar und wird auch so gezeigt, wie er gesendet wird (`CLASSIFY_PROMPT_VORSCHAU=1`). Ein Lauf
  in der Aktivität erscheint mit denselben Schritten und seinen echten Prompts und Antworten.
- **Info** (`/info`) — was paperlaiss ist, Links zum Repository und zu den Bausteinen.
- **Einstellungen** (`/einstellungen`) — jeder Wert der wirksamen Konfiguration (Datei plus
  Vorgaben; gespeichert werden nur geänderte Schlüssel).
- **Manuell klassifizieren** — eine Doc-ID, neu klassifiziert oder per OCR erzwungen.
- **JSON-API**: `/api/aktivitaet`, `/api/verlauf`, `/api/running`, `/api/trace/{id}`,
  `/api/reclassify`, `/api/config` (GET/POST), `/api/prompt-vorschau` (GET; POST mit einem Entwurf für die Live-Vorschau beim Bearbeiten).
- **Anmeldung** (`PANEL_AUTH`):
  - leer (Vorgabe) — Bearer-Token bzw. Cookie `PANEL_TOKEN`; ohne Token antwortet das Panel mit 503.
  - `none` — keine eigene Anmeldung, weil eine davorhängt (Reverse-Proxy mit Forward-Auth).
  - `tinysesam` — eigene Anmeldeseite über [TinySesam](https://github.com/Ollornog/TinySesam):
    OIDC (z. B. PocketID) über `PANEL_OIDC_ISSUER`, `PANEL_OIDC_CLIENT_ID`,
    `PANEL_OIDC_CLIENT_SECRET` (optional `PANEL_OIDC_GROUPS`, `PANEL_OIDC_NAME`); Benutzername +
    Passwort nur mit `PANEL_PASSWORD_LOGIN=1` (gedacht für ein Testsystem), erstes Konto aus
    `PANEL_ADMIN_USER` / `PANEL_ADMIN_PASSWORD`. Pflicht: `PANEL_BASE_URL` (die Adresse, unter der
    der Browser das Panel aufruft); die Benutzer liegen in `PANEL_AUTH_DB` (Vorgabe
    `/auth/tinysesam.db`, als Volume einhängen). Eine halbe OIDC-Konfiguration oder gar kein
    Anmeldeweg beendet den Container mit einer Meldung. Ein gesetzter `PANEL_TOKEN` gilt weiter für
    Skripte.
- **Unter einem Unterpfad** (etwa `https://paperless.example.com/paperlaiss`, neben Paperless auf
  derselben Domain): `PANEL_PFAD=/paperlaiss` setzen und den Präfix im Reverse-Proxy abschneiden
  lassen (Caddy: `handle_path /paperlaiss/* { reverse_proxy panel:8400 }`). Das Panel setzt den
  Präfix vor jeden Link und jeden API-Aufruf und startet uvicorn mit `--root-path`. Mit TinySesam
  muss `PANEL_BASE_URL` auf denselben Pfad enden — sonst startet der Container nicht.

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
Korrespondent: `email`, `domains`, `telefon`, `adresse`, `kundennummer`, `ustid`, `iban`, `kontext`, `aliase`.

Gepflegt **in Paperless selbst**: das Knopf-Skript blendet im Bearbeiten-Dialog eines Korrespondenten
einen Abschnitt *paperlaiss* ein (Kontext, Aliase, E-Mail, Mail-Domains, Kundennummer, USt-ID,
Telefon, Adresse), gespeichert zusammen mit Paperless' *Save* — erlaubt für alle, die den
Korrespondenten in Paperless ändern dürfen. Die Datei lässt sich auch von außen befüllen (eigenes
Stammdatensystem, ein Skript). Der Klassifizierer nutzt das dreifach:

- **Kandidaten finden, ohne KI-Aufruf.** Vor der Analyse sucht paperlaiss im Text nach den
  gespeicherten Kennungen *aller* Korrespondenten (USt-ID, IBAN, Mail, Domain, Kundennummer) und im
  Briefkopf (erste 1000 Zeichen) nach ihren Namen und Aliasen. Kam das Dokument per Mail, zählt auch
  die Absenderadresse. Alles Gefundene geht mit Kontext und Fundstelle als Kandidat an die Analyse.
  Die Absender-Mail ist ein starker Kandidat, keine Zuordnung: ein Portal verschickt Dokumente vieler
  Firmen von einer Adresse. (Bis 2026-09-27 riet ein eigener KI-Aufruf — „Pass 0“ — zuerst einen
  Absendernamen; die Suche ersetzt ihn.)
- **Eigene Firma.** `eigene_kennungen` (Namen, USt-IDs, IBANs, Mail-Domains/-Adressen) zählen nie als
  Absender — sie stehen auf fast jedem eingehenden Dokument. Die Analyse erfährt, wer „wir“ sind, und
  sucht das *Gegenüber*.
- **Stammdaten nachtragen.** `stammdaten_erfassen` (Vorgabe an): nach der Zuordnung werden USt-ID,
  IBAN, Mail/Domain, Telefon, Adresse und Kundennummer des Gegenübers aus dem Dokument **nur in leere
  Felder** geschrieben, nie überschreibend, mit Herkunft (`erfasst`), die der Paperless-Dialog zeigt.
  Die Absender-Mail wird nur übernommen, wenn sie nachweislich zu diesem Korrespondenten gehört.
  Schreibzugriffe laufen über eine gemeinsame Dateisperre mit dem Panel.

## Deployment (Docker)

Siehe [`deploy/docker-compose.example.yml`](../deploy/docker-compose.example.yml) und
[`deploy/.env.example`](../deploy/.env.example): den bestehenden `paperless`-Service um das
`./scripts`-Volume, `POST_CONSUME` und die `CLASSIFY_*`-Variablen erweitern und den `panel`-Service
ergänzen. `scripts/` muss für beide Container schreibbar sein.

### Knöpfe in Paperless (optional)

Ein Knopf **KI** (Zauberstab: optional ein Hinweis, dann liest paperlaiss das Dokument per
Mistral-OCR neu und klassifiziert es neu) — in der Dokumentansicht anstelle von Paperless' eigenem
*Suggest* (ausgeblendet) und als Eintrag im Menü **Actions** der Mehrfachauswahl. Kein Fork, keine
Tags, kein Workflow:

- Paperless führt bei jedem Containerstart Skripte aus `/custom-cont-init.d` aus (*Custom Container
  Initialization*). `deploy/paperless-knoepfe/10-paperlaiss-knoepfe.sh` kopiert
  `paperlaiss-knoepfe.js` ins Static-Verzeichnis und hängt eine `<script>`-Zeile in die Startseite —
  nach jedem Update erneut, nichts zu mergen.
- Die Knöpfe rufen das Panel direkt (`POST /knopf`). Der Browser schickt die **Paperless-Sitzung**
  mit; das Panel fragt damit bei Paperless, welche Dokumente dieser Nutzer ändern darf
  (`user_can_change`), und verarbeitet nur die. Ohne gültige Sitzung: 401.
- `PAPERLAISS_URL` (Paperless-Container): wo der Browser das Panel erreicht. Hinter demselben
  Reverse-Proxy genügt ein Pfad (Vorgabe `/paperlaiss`, ohne Präfix ans Panel weitergereicht); auf
  einem eigenen Port die volle Adresse. Dann zusätzlich `PAPERLAISS_KNOPF_ORIGIN` (Panel-Container)
  auf die Paperless-Adresse setzen, damit der Aufruf über Ursprünge hinweg CORS besteht.
- Bei *Alle auswählen* über mehrere Seiten werden nur die sichtbaren markierten verarbeitet, und der
  Menüeintrag sagt das. Das Panel fährt höchstens `PANEL_PARALLEL` (Vorgabe 2) Läufe gleichzeitig.
  Nach dem Lauf lädt die Seite neu, damit Paperless nicht seinen alten Stand über das Ergebnis
  speichert. Baut Paperless seine Seite um, fehlen die Knöpfe — Paperless selbst läuft weiter.

Daneben steht im Menü **Actions** ein zweiter Eintrag, **Export**. Der Dialog bietet zwei Varianten:

- **Ein PDF** — alle gewählten Dokumente zusammengefügt, ein Lesezeichen je Dokument (die eigenen
  Lesezeichen der Quelle darunter), optional **Seitenzahlen** („Seite i von n") und ein
  **Inhaltsverzeichnis** vorn: Titel und Seitenzahl springen zum Dokument, *In Paperless öffnen*
  öffnet es in Paperless.
- **Einzeln** — jedes Dokument als eigene PDF-Datei, byte-gleich mit dem, was Paperless liefert. Der
  Dateiname kommt aus einer **Vorlage** mit `{titel}`, `{korrespondent}`, `{typ}`, `{datum}`,
  `{jahr}`, `{monat}`, `{hinzugefuegt}`, `{id}`, `{asn}`, `{seiten}`, `{original}` und
  `{feld:<benutzerdefiniertes Feld>}`; optional **durchnummeriert** (`001_`), optional als **ZIP** und
  mit einem **Inhaltsverzeichnis-PDF**, dessen Einträge auf die Nachbardateien verlinken (Remote-Go-To
  und relativer URI — sie greifen, sobald das ZIP entpackt ist) und nach Paperless.
- Beide lassen sich nach jeder Variable oder jedem Feld **sortieren**, auf- oder absteigend. Quelle
  ist das Archiv-PDF, sonst das Original, wenn es ein PDF ist; alles andere wird übersprungen und
  genannt (im Dialog und im Verzeichnis unter *Nicht enthalten*).
- Rechte wie beim KI-Knopf, nur genügt **Leserecht**: das Panel prüft mit der Paperless-Sitzung des
  Nutzers, und ein nicht lesbares Dokument lehnt den ganzen Export ab (403), statt es still
  wegzulassen. Status und Download prüfen bei jedem Abruf erneut. Auch die Namen (Korrespondent, Typ,
  Felder) kommen über die Sitzung des Nutzers; die PDFs lädt das Panel mit seinem Token.
- Einstellungen am Panel: `EXPORT_MAX_DOKUMENTE` (Vorgabe 200), `EXPORT_MAX_MB` (200, Summe der
  PDFs), `EXPORT_PARALLEL` (1), `EXPORT_AUFBEWAHRUNG_MIN` (30 — danach sind Ergebnis und Dateien
  gelöscht), `EXPORT_TMP` (Ordner für Zwischendateien), `PAPERLESS_PUBLIC_URL` (Adresse von Paperless
  für die Links; leer: die Adresse der aufrufenden Paperless-Seite, nur vom selben Ursprung). Uhrzeiten
  folgen `PAPERLESS_TIME_ZONE`, sonst `TZ`. Das Panel muss als ein Prozess laufen (Aufträge liegen im
  Speicher).

## Konfiguration (`classify-config.json`)

| Key | Default | Bedeutung |
|---|---|---|
| `enabled` | `true` | Klassifizierer an/aus |
| `model` / `ocr_model` | `mistral-small-latest` / `mistral-ocr-latest` | Mistral-Modelle |
| `ocr_enabled` / `ocr_always` / `ocr_min_len` | `true` / `false` / `300` | OCR-Rescue-Verhalten |
| `ocr_regeln` | siehe unten | wann ein Text als zu schwach gilt und per OCR neu gelesen wird |
| `tagging_enabled` | `false` | KI vergibt inhaltliche Tags (aus: nur Typ/Korrespondent/Felder) |
| `marker_tag` | `ai-processed` | Tag, das gesetzt wird + als „schon erledigt"-Signal dient |
| `unsicher_tag` | – | optionaler Flag-Tag (per Name) |
| `summary_field` / `mail_context_field` / `mail_from_field` | – | optionale Felder (per Name) |
| `reserved_tags` | `[]` | Tag-Namen, die die KI nie vergibt (Status / Richtung / Marker) |
| `system_prompt` | – | leer = eingebauter Prompt (`{TYPES}` / `{TAGBLOCK}` werden ersetzt; das ältere `{TAGS}` bekommt die reine Tag-Liste; bei aktivem Tagging ohne beide Platzhalter wird der Tag-Block angehängt) |
| `tag_descriptions` | `{}` | Beschreibungen je Tag (nur bei aktivem Tagging) |
| `api_key_text` / `api_key_ocr` | – | leer = `MISTRAL_KEY` aus der Umgebung |

### OCR-Fallback (`ocr_regeln`)

Zwei Tore entscheiden, ob ein Dokument per Mistral-OCR neu gelesen wird:

1. **Vor der Analyse — Regeln.** OCR läuft, wenn der Text kürzer als `min_zeichen` ist
   (Vorgabe: `ocr_min_len`), weniger als `min_schluesselwoerter` aus `schluesselwoerter` enthält,
   weniger als ein echtes Wort je `max_zeichen_je_wort` Zeichen hat oder mehr als
   `max_muell_anteil` seiner sichtbaren Zeichen weder Buchstaben, Ziffern noch übliche
   Satzzeichen sind.
2. **Nach der Analyse — die KI und optionale Regeln.** Meldet das Modell unlesbaren Text
   (`nach_ki_meldung`, Vorgabe an) oder — wenn eingeschaltet — keinen Dokumenttyp
   (`wenn_kein_typ`) bzw. keinen Korrespondenten (`wenn_kein_korrespondent`), wird per OCR neu
   gelesen und in derselben Unterhaltung erneut analysiert. Nur, wenn vorher noch kein OCR lief —
   ein Dokument wird nie doppelt bezahlt.

**Neu klassifizieren aus Paperless** (Auslöser-Tag oder Hinweisfeld) läuft immer mit OCR. Die
Gründe stehen im Trace.

```json
"ocr_regeln": {"min_schluesselwoerter": 2, "max_muell_anteil": 0.25,
               "nach_ki_meldung": true, "wenn_kein_typ": false}
```

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

Icon: <a href="https://www.flaticon.com/authors/magnific" target="_blank" rel="noopener">Origami PNG Image by Magnific - flaticon.com</a>
