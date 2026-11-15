#!/usr/bin/env bash
# Builds the sample originals of tests/abbild_ocr_art.py with the tools that make such files in real life:
# Ghostscript (digital PDF, as an office suite or a print driver writes it), img2pdf (a scanner without OCR),
# OCRmyPDF/Tesseract (a scanner that lays an invisible text layer over the image), qpdf (mixed and letterhead).
# Content is made up. The files are committed; run this only to rebuild them, inside the Paperless image:
#
#   docker run --rm --entrypoint bash -u "$(id -u)" -v "$PWD/tests/fixtures/ocr-art:/out" \
#       ghcr.io/paperless-ngx/paperless-ngx:<version> /out/erzeugen.sh
set -euo pipefail
cd /out
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# A one-page letter with plenty of visible text.
{
  echo '%!PS'
  echo '/Helvetica-Bold findfont 16 scalefont setfont 72 760 moveto (Musterfirma GmbH) show'
  echo '/Helvetica findfont 11 scalefont setfont'
  y=720
  for zeile in "Musterweg 1, 12345 Musterstadt" "Rechnung Nr. 2026-0042 vom 15.11.2026" \
               "Sehr geehrte Damen und Herren," "fuer die Lieferung vom 10.11.2026 berechnen wir:" \
               "1 Stueck Pruefgeraet Typ A ............ 100,00 EUR" "1 Stueck Kabelsatz ................... 20,00 EUR" \
               "Summe netto ......................... 120,00 EUR" "Umsatzsteuer 19 % .................... 22,80 EUR" \
               "Summe brutto ........................ 142,80 EUR" "Zahlbar innerhalb von 14 Tagen ohne Abzug." \
               "Bankverbindung: Musterbank, IBAN DE00 0000 0000 0000 0000 00" "Mit freundlichen Gruessen" \
               "Ihre Musterfirma GmbH"; do
    printf '72 %d moveto (%s) show\n' "$y" "$zeile"
    y=$((y - 22))
  done
  echo 'showpage'
} > "$tmp/brief.ps"

# A letterhead without text: a bar at the top and a line at the bottom.
cat > "$tmp/kopf.ps" <<'PS'
%!PS
0.6 setgray 0 790 595 52 rectfill
0.3 setgray 40 60 515 2 rectfill
showpage
PS

gs -q -dNOPAUSE -dBATCH -dSAFER -sDEVICE=pdfwrite -sPAPERSIZE=a4 -o digital.pdf "$tmp/brief.ps"
gs -q -dNOPAUSE -dBATCH -dSAFER -sDEVICE=pnggray -r100 -sPAPERSIZE=a4 -o "$tmp/scan.png" "$tmp/brief.ps"
gs -q -dNOPAUSE -dBATCH -dSAFER -sDEVICE=pnggray -r100 -sPAPERSIZE=a4 -o "$tmp/kopf.png" "$tmp/kopf.ps"
img2pdf --pagesize A4 -o scan.pdf "$tmp/scan.png"
img2pdf --pagesize A4 -o "$tmp/kopf.pdf" "$tmp/kopf.png"
ocrmypdf -q -l deu --output-type pdf scan.pdf scan-ocr.pdf
qpdf --empty --pages digital.pdf scan.pdf digital.pdf -- gemischt.pdf
qpdf digital.pdf --underlay "$tmp/kopf.pdf" -- briefpapier.pdf
gs -q -dNOPAUSE -dBATCH -dSAFER -sDEVICE=jpeggray -dJPEGQ=70 -r100 -sPAPERSIZE=a4 -o foto.jpg "$tmp/brief.ps"
sha256sum digital.pdf scan.pdf scan-ocr.pdf gemischt.pdf briefpapier.pdf foto.jpg > SHA256SUMS
