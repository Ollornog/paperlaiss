# Mitwirken

<a href="../CONTRIBUTING.md">English</a> · <b>Deutsch</b>
<br /><br />

Danke für die Zeit. Dieses Projekt ist absichtlich klein; eine Änderung, die es klein lässt, ist
meistens die bessere.

## Grundregeln

1. **Tests gehören zur Änderung, nicht zur Nachbereitung.** Wer Verhalten ändert, ändert im selben
   Commit den Test. Doku und `CHANGELOG.md` wandern mit.
2. **Die Suite muss wiederholbar sein.** Sie bringt ihren eigenen frischen Zustand mit, braucht kein
   Netz und räumt auf. `./scripts/check.sh` zweimal laufen lassen — beide Läufe grün. Ein Test, der
   beim zweiten Lauf rot wird, ist kaputt, nicht der Code.
3. **Keine persönlichen Namen im Repo.** Keine privaten Hostnamen, keine Firmendomains, keine
   Kundennamen — weder im Code noch in Beispieldaten, Tests, Doku oder Commit-Messages. Stattdessen
   `example.com` und echte Werte über Umgebungsvariablen. `tests/test_repo.py` prüft das.
4. **Secrets kommen aus der Umgebung.** `PAPERLESS_TOKEN` und `MISTRAL_KEY` werden aus der Umgebung
   gelesen; die Config trägt keine Zugangsdaten. Das bleibt so.

## Ablauf

Gearbeitet wird auf einem Feature-Branch. Dort läuft keine CI — `ci-local` bzw.
`./scripts/check.sh` ist das Sicherheitsnetz. Dann ein Pull Request; die CI läuft am PR und auf
`main`.

```bash
git switch -c meine-aenderung
git config core.hooksPath .githooks    # einmal pro Klon
# ... bauen, dann:
./scripts/check.sh
git commit -am "Beschreibe die Änderung, nicht den Diff"
git push -u origin meine-aenderung
```

Der Klassifizierer ist reine Standardbibliothek — kein Installationsschritt, um an `classify.py`
mitzuarbeiten. Das Panel braucht FastAPI (`pip install -r panel/requirements.txt`), wenn man es
anfasst.

## Stil

- Kommentare erklären das **Warum**, nie was die nächste Zeile tut. Braucht eine Zeile einen
  Kommentar, um lesbar zu sein, gehört die Zeile umgeschrieben.
- Die Oberfläche spricht Deutsch; Bezeichner im Code sind englisch.
- Dateien sind UTF-8 ohne BOM. Umlaute werden als Umlaute geschrieben.
- Keine neue Abhängigkeit in `classify.py` — es bleibt bewusst stdlib-only. Im Panel keine neue
  Abhängigkeit ohne einen Grund, der in einen Satz passt.

## Fehler melden

Was war erwartet, was passierte, und die kleinste Eingabe, die es reproduziert — ein Dokumenttyp
oder Feld-Aufbau, die relevanten `classify-config.json`-Keys und ein Trockenlauf
(`CLASSIFY_DRY=1 CLASSIFY_DOC=<id>`), wo er hilft.

<br /><br />
<p align="right"><img src="../docs/toilet-roll.png" alt="paperlaiss" width="60" height="60"></p>
