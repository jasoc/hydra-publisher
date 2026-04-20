#!/usr/bin/env bash
# record.sh — avvia playwright codegen su un URL di marketplace
#
# Uso:
#   ./playwright/record.sh                         # apre browser vuoto
#   ./playwright/record.sh https://www.vinted.it/items/new
#   ./playwright/record.sh facebook                # shortcut predefiniti
#   ./playwright/record.sh vinted
#   ./playwright/record.sh subito
#
# L'output viene copiato automaticamente negli appunti (se xclip/wl-copy è disponibile).
# Premi Ctrl+C nel terminale per fermare la registrazione.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"
PLAYWRIGHT="$VENV/bin/playwright"

# ── Shortcut predefiniti ──────────────────────────────────────────────────────
declare -A SHORTCUTS=(
  [facebook]="https://www.facebook.com/marketplace/create/item"
  [vinted]="https://www.vinted.it/items/new"
  [subito]="https://www.subito.it/inserisci-annuncio"
  [ebay]="https://www.ebay.it/sl/sell"
)

URL="${1:-}"

if [[ -z "$URL" ]]; then
  echo "Uso: $0 <url|shortcut>"
  echo ""
  echo "Shortcut disponibili:"
  for key in "${!SHORTCUTS[@]}"; do
    echo "  $key  →  ${SHORTCUTS[$key]}"
  done
  echo ""
  read -rp "URL o shortcut: " URL
fi

# Risolvi shortcut
if [[ -v SHORTCUTS[$URL] ]]; then
  RESOLVED="${SHORTCUTS[$URL]}"
  echo "→ Shortcut '$URL' risolto in: $RESOLVED"
  URL="$RESOLVED"
fi

# ── Output file ───────────────────────────────────────────────────────────────
PROVIDER_SLUG=$(echo "$URL" | sed 's|https\?://||; s|/.*||; s|www\.||; s|\..*||')
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="$SCRIPT_DIR/recorded/${PROVIDER_SLUG}_${TIMESTAMP}.py"
mkdir -p "$SCRIPT_DIR/recorded"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Playwright codegen                                      ║"
echo "║                                                          ║"
echo "║  1. Interagisci con il form nel browser                  ║"
echo "║  2. Il codice appare nel pannello laterale               ║"
echo "║  3. Chiudi il browser per salvare                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  URL:    $URL"
echo "  Output: $OUTPUT_FILE"
echo ""

# ── Avvia codegen ─────────────────────────────────────────────────────────────
"$PLAYWRIGHT" codegen \
  --target python \
  --output "$OUTPUT_FILE" \
  "$URL"

echo ""
echo "✓ Registrazione salvata in: $OUTPUT_FILE"
echo ""

# ── Genera il YAML automaticamente ───────────────────────────────────────────
PYTHON="$VENV/bin/python3"
EXTRACT="$SCRIPT_DIR/extract.py"

echo "Generazione selectors/${PROVIDER_SLUG}.yaml..."
if "$PYTHON" "$EXTRACT" "$OUTPUT_FILE" --provider "$PROVIDER_SLUG"; then
  YAML_FILE="$(dirname "$SCRIPT_DIR")/hydra-publisher/src-tauri/resources/python/providers/selectors/${PROVIDER_SLUG}.yaml"
  echo ""
  echo "── YAML generato ───────────────────────────────────────────"
  cat "$YAML_FILE" 2>/dev/null || true
  echo "────────────────────────────────────────────────────────────"
else
  echo "⚠ extract.py fallito — controlla il file manualmente: $OUTPUT_FILE"
fi

# ── Copia negli appunti ───────────────────────────────────────────────────────
if command -v wl-copy &>/dev/null; then
  wl-copy < "$OUTPUT_FILE"
  echo "✓ Codegen copiato negli appunti (wl-copy)"
elif command -v xclip &>/dev/null; then
  xclip -selection clipboard < "$OUTPUT_FILE"
  echo "✓ Codegen copiato negli appunti (xclip)"
fi

echo ""
echo "Prossimi passi:"
echo "  1. Controlla i TODO in providers/selectors/${PROVIDER_SLUG}.yaml"
echo "  2. Se il provider non esiste ancora: crea providers/${PROVIDER_SLUG}.py"
echo "     (copia vinted.py come template, cambia solo il nome)"
echo "  3. Registra in server.py → PROVIDERS se non già presente"
