# paperlaiss

Grounded Dokumenten-Klassifizierer für **Paperless-ngx** — ein schlanker, eigener Ersatz für
[paperless-ai](https://github.com/clusterzx/paperless-ai). Läuft als `POST_CONSUME_SCRIPT`
(oder manuell / per Panel) und schreibt Metadaten direkt über die Paperless-REST-API zurück.

Entstanden als BrunPower-Konnektor, aber **mandantenunabhängig**: alle Feld-/Tag-Referenzen
werden per *Name* gegen die API aufgelöst, alles Verhalten ist per Config schaltbar.

## Was es macht

- **Dokumenttyp** + **Korrespondent** bestimmen — mit **Feedback-Loop** gegen den Bestand
  (Token-Match + LLM-Auflösung), der Dubletten/Halluzinate verhindert (kein „STRATO GmbH" neben „Strato").
- **Custom-Fields** typgerecht füllen (drei-Wege je Feld: Wert / `null`=leeren / `BEHALTEN`=unsicher).
- **OCR-Rescue**: schwacher/Müll-Text wird per **Mistral-OCR** neu gelesen (auch von der KI anforderbar).
- **Dokumentdatum** korrigieren (echtes Ausstellungsdatum statt referenzierter Daten im Text).
- **Self-Repair**: bei API-Validierungsfehlern korrigiert die KI die Feldwerte in einer Ping-Pong-Schleife.
- Optional (per Config aktivierbar): inhaltliches **Tagging**, adaptive **Zusammenfassung**,
  **Redo aus Paperless** (Trigger-Tag + Hinweis-Feld), **Herkunft-Kontext** (Mail-/Chat-Anschreiben).

**Bewusst NICHT enthalten:** Owner-/Rechte-Vergabe (macht der Paperless-Konsumpfad / `post-consume.sh`),
Vertrags-/Geräte-Verknüpfungen, Steuer-Automatik — das ist mandantenspezifisch.

## Setup

1. **Secrets als ENV** (nie in die Config/ins Repo):
   ```bash
   export PAPERLESS_TOKEN=<paperless-api-token>
   export MISTRAL_KEY=<mistral-api-key>
   ```
2. **`classify-config.json`** anpassen (Modell, `tagging_enabled`, `marker_tag`, `reserved_tags`, …).
3. Als Post-Consume in Paperless einhängen:
   ```
   PAPERLESS_POST_CONSUME_SCRIPT=/pfad/classify.py
   ```
   (Paperless setzt `DOCUMENT_ID`.) Python-Standardbibliothek genügt — keine Extra-Pakete.

## Manuell / Test

```bash
CLASSIFY_DRY=1  CLASSIFY_DOC=<id>  python3 classify.py     # nur ausgeben, nichts schreiben
CLASSIFY_FORCE=1 CLASSIFY_DOC=<id> python3 classify.py     # schon-klassifizierte neu machen
CLASSIFY_FORCE_OCR=1 CLASSIFY_DOC=<id> python3 classify.py # Mistral-OCR erzwingen
```

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
| `reserved_tags` | `[]` | Tag-Namen, die die KI nie vergibt (Status/Richtung/Marker) |
| `system_prompt` | – | leer = eingebauter Prompt (`{TYPES}` / `{TAGBLOCK}` werden ersetzt) |
| `tag_descriptions` | `{}` | Beschreibungen je Tag (nur bei aktivem Tagging) |
| `api_key_text` / `api_key_ocr` | – | leer = `MISTRAL_KEY` aus ENV |
