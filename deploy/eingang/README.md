# Eingangsordner → Paperless

`eingang.py` beobachtet je Konto einen Ordner (etwa eine per Seafile-Client gespiegelte Bibliothek).
Jede fertig geschriebene Datei wird mit dem **API-Schlüssel dieses Kontos** hochgeladen, gehört in
Paperless also der Person, der der Ordner gehört. `tags` (IDs oder Namen, je Konto oder für alle)
gehen mit dem Upload — Paperless-Workflows können nicht nach Besitzer filtern.

**Mit Archiv** (`eingang` und `archiv` gesetzt, seit 0.10), etwa eine Bibliothek „Paperless“ mit den
Ordnern `Inbox` und `Archiv`:

| Ergebnis | Was mit der Datei passiert |
|---|---|
| Import erfolgreich oder Dublette (schon in Paperless) | nach `Archiv/<JJJJ.MM.TT> <Originalname>`, Datum = Tag des Imports in `zeitzone` (Vorgabe Europe/Berlin); Name belegt → ` (2)`, ` (3)` …; Unterordner bleiben |
| Import gescheitert / abgelehnt | bleibt in `Inbox`, daneben `<name>.fehler.txt` mit dem Grund; neuer Versuch, sobald die Datei sich ändert oder die Notiz gelöscht wird |
| Task läuft noch | bleibt liegen, wird nicht doppelt hochgeladen |

**Ohne Archiv** (bis 0.9): Erfolg und Dublette werden gelöscht, ein Fehlschlag wandert nach
`_Fehler/` samt `<name>.txt` mit dem Grund.

Nicht angefasst werden versteckte Dateien, Office-Sperrdateien (`~$…`), Temp-Dateien (`.part`,
`.tmp`, …), Fehlernotizen und alles unter `_…`-Ordnern. „Fertig geschrieben“ heißt: älter als
`ruhezeit_s` und in zwei Runden gleich groß.

Einrichtung: Konfiguration als JSON (siehe Kopf von `eingang.py`), Schlüssel in einer Umgebungsdatei
mit 0600, Dienst wie in `paperless-eingang.service`. Nur Python-Standardbibliothek.
