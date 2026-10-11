# Eingangsordner → Paperless

`eingang.py` beobachtet je Konto einen Ordner (etwa eine per Seafile-Client gespiegelte Bibliothek
„Paperless-Eingang“). Jede fertig geschriebene Datei wird mit dem **API-Schlüssel dieses Kontos**
hochgeladen, gehört in Paperless also der Person, der der Ordner gehört. Danach wird sie aus dem
Ordner entfernt; ein Sync-Client überträgt das Löschen zurück.

| Ergebnis | Was mit der Datei passiert |
|---|---|
| Import erfolgreich | gelöscht |
| Dublette (schon in Paperless) | gelöscht |
| Import gescheitert / abgelehnt | nach `_Fehler/`, daneben `<name>.txt` mit dem Grund |
| Task läuft noch | bleibt liegen, wird nicht doppelt hochgeladen |

Nicht angefasst werden versteckte Dateien, Office-Sperrdateien (`~$…`), Temp-Dateien (`.part`,
`.tmp`, …) und alles unter `_…`-Ordnern. „Fertig geschrieben“ heißt: älter als `ruhezeit_s` und in
zwei Runden gleich groß.

Einrichtung: Konfiguration als JSON (siehe Kopf von `eingang.py`), Schlüssel in einer Umgebungsdatei
mit 0600, Dienst wie in `paperless-eingang.service`. Nur Python-Standardbibliothek.
