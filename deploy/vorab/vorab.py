#!/usr/bin/env python3
"""paperlaiss — Einstieg für PAPERLESS_PRE_CONSUME_SCRIPT: ruft die Vorab-Schritte nacheinander auf.

Paperless kennt nur EIN Pre-Consume-Skript. Jeder Schritt entscheidet selbst, ob die Datei ihn
betrifft, und lässt alles andere unberührt:

  mailbilder.py   eine .eml bekommt Kopf und große Bildseiten (Mail-Regel „ganze Mail“)
  leerseiten.py   ein PDF verliert komplett weiße Seiten

Die Schritte liegen im selben Ordner wie dieses Skript. Es endet IMMER mit 0 — ein fehlender,
abgestürzter oder hängender Schritt hält keinen Import auf; jeder Schritt ersetzt die Arbeitskopie
nur am Ende und atomar, ein Abbruch lässt sie also heil.
"""
import os
import subprocess
import sys

SCHRITTE = ("mailbilder.py", "leerseiten.py")
FRIST = 300                     # Sekunden je Schritt


def main():
    ordner = os.path.dirname(os.path.abspath(__file__))
    for name in SCHRITTE:
        skript = os.path.join(ordner, name)
        if not os.path.isfile(skript):
            print(f"vorab: {name} fehlt — übersprungen", file=sys.stderr)
            continue
        try:
            subprocess.run([sys.executable, skript], timeout=FRIST)
        except Exception as e:
            print(f"vorab: {name} abgebrochen: {e!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
