# Sicherheitsrichtlinie

<a href="../SECURITY.md">English</a> · <b>Deutsch</b>
<br /><br />

## Schwachstellen melden

Bitte vertraulich über GitHubs
[private Meldung](https://github.com/Ollornog/paperlaiss/security/advisories/new) statt über ein
öffentliches Issue. Eine erste Antwort kommt binnen einer Woche.

## Umfang und Entwurfsentscheidungen, die man kennen sollte

- **Secrets kommen aus der Umgebung, nie aus der Config oder dem Repo.** `PAPERLESS_TOKEN` und
  `MISTRAL_KEY` werden aus Umgebungsvariablen gelesen; die Config-Keys `api_key_text` /
  `api_key_ocr` sind nur ein Override und stehen standardmäßig leer. Eine eingecheckte
  `classify-config.json` trägt keine Zugangsdaten.
- **Der Klassifizierer schreibt mit einem vollen API-Token nach Paperless.** Vergib ein Token,
  das nur so viel darf wie nötig. Er ändert Typ, Korrespondent, Custom-Fields, das Datum und — nur
  bei `tagging_enabled` — Tags; owner und Rechte fasst er per Entwurf nie an.
- **Dokumenttext geht an einen Dritten.** Grounding und OCR rufen die Mistral-API, Dokumentinhalt
  verlässt also die Maschine. Genau das ist der Zweck des Werkzeugs, aber es ist eine bewusst zu
  treffende Datenfluss-Entscheidung; `content_max_len` begrenzt die gesendete Menge.
- **Das Panel ist ohne `PANEL_TOKEN` unauthentifiziert.** Ohne es sind Dashboard, JSON-API und die
  Reclassify-Aktion für jeden offen, der den Port erreicht. In Prod einen Reverse-Proxy mit
  Forward-Auth oder OIDC davorsetzen und den Port ans interne Netz binden.
- **Ingest-Tokens sind Befugnisse.** Jeder Eintrag in `INGEST_TOKENS` erlaubt seinem Inhaber, ein
  Dokument mit festem Quelle-Tag nach Paperless zu schieben. Wie Passwörter behandeln, eines je
  Eingang, ein geleaktes durch Ändern der Map rotieren.
- **`reserved_tags` bleiben beim Writeback geschützt.** Status-, Richtungs- und Marker-Tags aus
  dieser Liste vergibt das Modell nie und sie bleiben beim Patchen der Metadaten erhalten.

## Nicht im Umfang

Alles, was der Betreiber von Natur aus darf (das Token auf ein beliebiges Dokument richten, jeden
Inhalt ans Modell senden), und Überlastung durch sehr große Uploads oder Dokumente.

<br /><br />
<p align="right"><img src="../docs/toilet-roll.png" alt="paperlaiss" width="60" height="60"></p>
