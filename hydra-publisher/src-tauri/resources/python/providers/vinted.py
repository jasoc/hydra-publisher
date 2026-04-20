"""
Vinted provider.

I selettori del form stanno in selectors/vinted.yaml.
Aggiorna quello quando il sito cambia DOM — questo file non va toccato.

Login: apre vinted.it usando il profilo persistente. L'utente effettua login
manualmente dal pannello impostazioni quando necessario.
"""

import os
import time
from typing import Any

from base import SeleniumProvider, FormFiller

# In dev mode the YAML lives in selectors/; in the bundled app everything is
# flattened into the same directory as this file.
_SELECTORS = os.path.join(os.path.dirname(__file__), "selectors", "vinted.yaml")
if not os.path.exists(_SELECTORS):
    _SELECTORS = os.path.join(os.path.dirname(__file__), "vinted.yaml")

# Selettore che indica "utente loggato" (navbar con icona profilo).
# Aggiorna se Vinted cambia la struttura della nav.
class VintedProvider(SeleniumProvider):

    _filler = FormFiller(_SELECTORS)

    # ── Login ─────────────────────────────────────────────────────────────────

    def login(self, driver: Any) -> None:
        driver.get("https://www.vinted.it")
        print("[Vinted] Browser ready for manual login.")

    # ── Publish ───────────────────────────────────────────────────────────────

    def publish(self, article: dict, driver: Any) -> None:
        print(f"[Vinted] Pubblicazione: {article.get('name', '?')}")
        driver.get(self._filler.publish_url)
        time.sleep(2)           # attendi rendering React
        self._filler.fill(article, driver)
        print(f"[Vinted] Completato: {article.get('name', '?')}")
