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
   Unterstützt werden die drei neuesten stable Python-Reihen (derzeit 3.12–3.14); die
   Untergrenze steigt mit jeder neuen Python-Reihe mit, und zwar bewusst.

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
- **Ablauf & Prompt** (`/ablauf`) — jeder Schritt eines Laufs mit den aktuellen Einstellungen und der
  System-Prompt von Pass 1 genau so, wie er gesendet wird (gebaut von `classify.py` selbst:
  `CLASSIFY_PROMPT_VORSCHAU=1`).
- **JSON-API**: `/api/stats`, `/api/feed`, `/api/running`, `/api/trace/{id}`, `/api/reclassify`,
  `/api/config` (GET/POST). Eine übergeordnete Plattform kann dieselben Endpunkte konsumieren.
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
| `ocr_regeln` | siehe unten | wann ein Text als zu schwach gilt und per OCR neu gelesen wird |
| `tagging_enabled` | `false` | KI vergibt inhaltliche Tags (aus: nur Typ/Korrespondent/Felder) |
| `marker_tag` | `ai-processed` | Tag, das gesetzt wird + als „schon erledigt"-Signal dient |
| `unsicher_tag` / `redo_tag` | – | optionale Flag-/Redo-Tags (per Name) |
| `summary_field` / `hinweis_field` / `mail_context_field` / `mail_from_field` | – | optionale Felder (per Name) |
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
