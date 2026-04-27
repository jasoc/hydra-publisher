"""
Subito.it provider — Selenium implementation.

Flow verified manually via MCP Chrome DevTools on 2026-04-07.
Full notes: docs/subito-manual-publish-session.md

Key findings:
  - Modal dialog blocks clicks on load → hide via JS
  - File input is display:none → make visible via JS before send_keys
  - Condizione is a React-Select → JS .click() does NOT open it;
    use el.click() (real CDP click) + send_keys(Keys.ARROW_DOWN),
    then poll [role="option"] elements and click via JS
  - Comune is AJAX autocomplete → set value via React native setter hack
    + dispatch 'input' event, poll [role="option"], click
  - Phone is also React-controlled → same setter trick
  - Post-publish: 2 upsell screens (modal + page); skip both
"""

import os
import re
import time
import urllib.parse
from typing import Any

from selenium.common.exceptions import TimeoutException, ElementNotInteractableException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from base import SeleniumProvider

# ── Category map ──────────────────────────────────────────────────────────────
# Keys: app category (from categories.model.ts, case-insensitive lookup).
# Values: Subito numeric category ID.
# Subito has far fewer categories than Vinted — many app categories map to
# the same Subito bucket.
CATEGORY_MAP: dict[str, int] = {
    # Casa e cucina / Ufficio e casa
    "Arredamento": 14,
    "Elettrodomestici cucina": 14,
    "Pentole e padelle": 14,
    "Utensili cucina": 14,
    "Stoviglie": 14,
    "Biancheria letto": 14,
    "Tende e tapparelle": 14,
    "Tappeti": 14,
    "Candele e profumi casa": 14,
    "Illuminazione": 14,
    "Cornici": 14,
    "Specchi": 14,
    "Vasi": 14,
    "Decorazioni parete": 14,
    "Materiale ufficio": 14,
    "Attrezzi e bricolage": 14,
    "Giardino": 14,
    "Animali": 14,
    # Elettronica
    "Videogiochi e console": 22,
    "Console": 22,
    "Computer portatili": 10,
    "Computer desktop": 10,
    "Componenti PC": 10,
    "Tastiere": 10,
    "Mouse": 10,
    "Monitor": 10,
    "Stampanti": 10,
    "Cuffie e auricolari": 10,
    "Altoparlanti e speaker": 10,
    "Audio e hi-fi": 10,
    "Fotocamere": 10,
    "Obiettivi": 10,
    "Tablet": 10,
    "E-reader": 10,
    "Televisori": 10,
    "Proiettori": 10,
    "Smartwatch": 10,
    "Fitness tracker": 10,
    "Caricabatterie e power bank": 10,
    "Cavi e adattatori": 10,
    # Telefonia
    "Smartphone": 12,
    "Accessori telefono": 12,
    # Abbigliamento (donna + uomo + bambini generico)
    "Vestiti donna": 16,
    "Giacche e cappotti donna": 16,
    "Maglioni e pullover donna": 16,
    "Abiti donna": 16,
    "Gonne": 16,
    "Top e t-shirt donna": 16,
    "Jeans donna": 16,
    "Pantaloni donna": 16,
    "Pantaloncini donna": 16,
    "Costumi da bagno donna": 16,
    "Lingerie e pigiami": 16,
    "Abbigliamento sportivo donna": 16,
    "Scarpe donna": 16,
    "Stivali donna": 16,
    "Sandali donna": 16,
    "Tacchi": 16,
    "Sneakers donna": 16,
    "Borse": 16,
    "Zaini donna": 16,
    "Pochette": 16,
    "Portafogli donna": 16,
    "Cinture donna": 16,
    "Cappelli donna": 16,
    "Gioielli donna": 16,
    "Sciarpe e scialli donna": 16,
    "Occhiali da sole donna": 16,
    "Orologi donna": 16,
    "Vestiti uomo": 16,
    "Giacche e cappotti uomo": 16,
    "Camicie uomo": 16,
    "T-shirt uomo": 16,
    "Maglioni e pullover uomo": 16,
    "Completi e blazer uomo": 16,
    "Pantaloni uomo": 16,
    "Jeans uomo": 16,
    "Pantaloncini uomo": 16,
    "Costumi da bagno uomo": 16,
    "Abbigliamento sportivo uomo": 16,
    "Scarpe uomo": 16,
    "Stivali uomo": 16,
    "Sneakers uomo": 16,
    "Scarpe formali": 16,
    "Cinture uomo": 16,
    "Cappelli uomo": 16,
    "Gioielli uomo": 16,
    "Cravatte e papillon": 16,
    "Orologi uomo": 16,
    "Occhiali da sole uomo": 16,
    "Abbigliamento bambina": 16,
    "Abbigliamento bambino": 16,
    "Scarpe bambini": 16,
    "Articoli griffati": 16,
    "Borse griffate": 16,
    "Scarpe griffate": 16,
    # Bellezza
    "Make-up": 16,
    "Profumi": 16,
    "Cura del viso": 16,
    "Cura del corpo": 16,
    # Bambini (non-abbigliamento)
    "Giocattoli": 14,
    "Peluche": 14,
    "Costruzioni": 14,
    "Bambole": 14,
    "Passeggini e carrozzine": 14,
    "Seggiolini auto": 14,
    "Arredamento bambini": 14,
    # Sport
    "Ciclismo": 20,
    "Fitness e palestra": 20,
    "Corsa": 20,
    "Yoga e pilates": 20,
    "Campeggio": 20,
    "Arrampicata": 20,
    "Pesca": 20,
    "Nuoto": 20,
    "Surf e SUP": 20,
    "Calcio": 20,
    "Basket": 20,
    "Pallavolo": 20,
    "Tennis": 20,
    "Padel": 20,
    "Golf": 20,
    "Equitazione": 20,
    "Skateboard": 20,
    "Boxe e arti marziali": 20,
    "Sci": 20,
    "Snowboard": 20,
    "Pattinaggio": 20,
    # Hobby e collezionismo
    "Carte collezionabili": 20,
    "Giochi da tavolo": 20,
    "Puzzle": 20,
    "Monete e banconote": 20,
    "Francobolli": 20,
    "Arte e artigianato": 20,
    # Intrattenimento
    "Libri": 19,
    "Narrativa": 19,
    "Saggistica": 19,
    "Fumetti e manga": 19,
    "Riviste": 19,
    "Musica": 20,
    "Vinile": 20,
    "CD": 20,
    "DVD e Blu-ray": 20,
    "Strumenti musicali": 20,
    "Chitarre": 20,
    # Veicoli
    "Auto": 101,
    "Moto": 102,
    "Ricambi auto": 101,
}
# Build a case-insensitive lookup (the publish code lowercases the input)
_CATEGORY_MAP_LOWER: dict[str, int] = {k.lower(): v for k, v in CATEGORY_MAP.items()}
DEFAULT_CATEGORY = 14

# ── Condition map ─────────────────────────────────────────────────────────────
CONDITION_MAP: dict[str, str] = {
    "nuovo":               "Nuovo - mai usato in confezione originale",
    "new":                 "Nuovo - mai usato in confezione originale",
    "come nuovo":          "Come nuovo - perfetto o ricondizionato",
    "like new":            "Come nuovo - perfetto o ricondizionato",
    "usato - come nuovo":  "Come nuovo - perfetto o ricondizionato",
    "ottimo":              "Ottimo - poco usato e ben conservato",
    "usato - ottimo":      "Ottimo - poco usato e ben conservato",
    "buono":               "Buono - usato ma ben conservato",
    "usato - buono":       "Buono - usato ma ben conservato",
    "usato":               "Buono - usato ma ben conservato",
    "danneggiato":         "Danneggiato - usato con parti guaste",
    "damaged":             "Danneggiato - usato con parti guaste",
}
DEFAULT_CONDITION = "Buono - usato ma ben conservato"

# ── Sport type map (only relevant for Subito category 20 = Sports) ────────────
SPORT_TYPE_MAP: dict[str, str] = {
    "ciclismo": "Ciclismo",
    "calcio": "Calcio",
    "basket": "Basket",
    "pallavolo": "Volley",
    "nuoto": "Acquatici",
    "surf e sup": "Acquatici",
    "sci": "Sci e Snowboard",
    "snowboard": "Sci e Snowboard",
    "golf": "Golf",
    "fitness e palestra": "Palestra",
    "corsa": "Palestra",
    "yoga e pilates": "Palestra",
    "boxe e arti marziali": "Palestra",
    "equitazione": "Outdoor",
    "campeggio": "Outdoor",
    "arrampicata": "Outdoor",
    "pesca": "Outdoor",
    "skateboard": "Outdoor",
    "pattinaggio": "Outdoor",
    "tennis": "Altro",
    "padel": "Altro",
    "carte collezionabili": "Altro",
    "giochi da tavolo": "Altro",
    "puzzle": "Altro",
    "monete e banconote": "Altro",
    "francobolli": "Altro",
    "arte e artigianato": "Altro",
    "musica": "Altro",
    "vinile": "Altro",
    "cd": "Altro",
    "dvd e blu-ray": "Altro",
    "strumenti musicali": "Altro",
    "chitarre": "Altro",
}
DEFAULT_SPORT_TYPE = "Altro"

# ── JS snippets ───────────────────────────────────────────────────────────────

# Set value on a React-controlled input/textarea bypassing controlled component
_JS_REACT_SET = """
(function(el, val) {
  var p = el.tagName === 'TEXTAREA'
    ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(p, 'value').set.call(el, val);
  el.dispatchEvent(new Event('input',  {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
})(arguments[0], arguments[1]);
"""

# Click a react-select option by keyword match on textContent
_JS_CLICK_OPTION = """
var opts = document.querySelectorAll('[role="option"]');
for (var i = 0; i < opts.length; i++) {
  if (opts[i].textContent.indexOf(arguments[0]) !== -1) { opts[i].click(); return true; }
}
return false;
"""


class SubitoProvider(SeleniumProvider):
    """
    Publishes articles on Subito.it via Selenium.

    Required article keys: name, description, price, photos, folderPath
    Optional:  category, condition, city, phone
    """

    DEFAULT_CITY  = os.environ.get("SUBITO_DEFAULT_CITY",  "Catania")
    DEFAULT_PHONE = os.environ.get("SUBITO_DEFAULT_PHONE", "3331234567")

    def login(self, driver: Any) -> None:
        """Open Subito homepage for optional manual login in persistent profile."""
        driver.get("https://www.subito.it/")
        print("[Subito] Browser ready for manual login.")

    def publish(self, article: dict, driver: Any) -> str:
        """Publish a listing and return the Subito listing UUID."""
        title       = article.get("name", "")
        description = article.get("description", "")
        price       = str(int(float(article.get("price", 0))))
        photos      = article.get("photos", [])
        folder      = article.get("folderPath", "")
        city        = article.get("city")  or self.DEFAULT_CITY
        phone       = article.get("phone") or self.DEFAULT_PHONE
        condition   = CONDITION_MAP.get(
                          str(article.get("condition", "")).strip().lower(),
                          DEFAULT_CONDITION)
        category_id = _CATEGORY_MAP_LOWER.get(
                          str(article.get("category", "")).strip().lower(),
                          DEFAULT_CATEGORY)

        # 1. Navigate directly to the insertion form
        driver.get(
            f"https://inserimento.subito.it/"
            f"?category={category_id}"
            f"&subject={urllib.parse.quote(title)}"
            f"&from=vendere"
        )
        try:
            WebDriverWait(driver, 25).until(
                lambda d: d.find_elements(By.ID, "price")
                or d.find_elements(By.CSS_SELECTOR, "textarea")
            )
        except TimeoutException as e:
            raise RuntimeError(
                "Subito form non caricato in tempo (price/textarea assenti). "
                f"URL attuale: {driver.current_url}"
            ) from e
        time.sleep(0.4)

        # 2. Close modal + show file input
        driver.execute_script("""
            var d = document.querySelector('[role="dialog"]');
            if (d) d.style.display = 'none';
            var fi = document.querySelector('input[type="file"]');
            if (fi) fi.style.cssText =
              'display:block!important;opacity:1!important;position:fixed!important;'
              + 'top:10px;left:10px;z-index:99999;width:200px;height:30px;';
        """)

        # 3. Fill description + price via React setter
        driver.execute_script(_JS_REACT_SET,
                              driver.find_element(By.CSS_SELECTOR, "textarea"),
                              description)
        driver.execute_script(_JS_REACT_SET,
                              driver.find_element(By.ID, "price"),
                              price)

        # 4. Condizione — react-select dropdown
        keyword = condition.split(" - ")[0]
        self._select_react_option(driver, "Condizione", keyword)

        # 4b. Tipologia (sportType) — only present for some categories (e.g. Sports/20)
        sport_type_fields = driver.find_elements(
            By.CSS_SELECTOR, 'input[aria-label="Tipologia"]')
        if sport_type_fields:
            cat_str = str(article.get("category", "")).strip().lower()
            sport_keyword = SPORT_TYPE_MAP.get(cat_str, DEFAULT_SPORT_TYPE)
            self._select_react_option(driver, "Tipologia", sport_keyword)

        # 5. Photos — re-show file input after React re-render, send paths
        if photos:
            driver.execute_script("""
                var fi = document.querySelector('input[type="file"]');
                if (fi) fi.style.cssText =
                  'display:block!important;opacity:1!important;position:fixed!important;'
                  + 'top:10px;left:10px;z-index:99999;width:200px;height:30px;';
            """)
            file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            for photo in photos:
                path = photo if os.path.isabs(photo) else os.path.join(folder, photo)
                if os.path.exists(path):
                    file_input.send_keys(path)
                    time.sleep(1.5)
                else:
                    print(f"[Subito] Photo not found, skipping: {path}")

        # 6. Comune (AJAX autocomplete) — real keystrokes trigger the AJAX
        loc_input = driver.find_element(By.ID, "location")
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", loc_input)
        time.sleep(0.3)
        loc_input.click()
        loc_input.clear()
        loc_input.send_keys(city)
        # Wait for the autocomplete dropdown to show an option
        loc_option = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                '#autocomplete-location-menu li[role="option"]')))
        time.sleep(0.3)
        loc_text = loc_option.text.strip()[:40]
        loc_option.click()
        print(f"[Subito] Comune: clicked '{loc_text}'")

        # 6b. Phone
        driver.execute_script(_JS_REACT_SET,
                              driver.find_element(By.ID, "phone"),
                              phone)

        # 7. Click Continua
        time.sleep(1)
        continua = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH,
                 "//button[contains(@class,'sbt-button') and "
                 "normalize-space()='Continua']")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});",
                              continua)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", continua)
        print("[Subito] Clicked Continua — waiting for next page…")

        # Wait for URL to change away from the insertion form
        WebDriverWait(driver, 20).until(
            lambda d: "/anteprima" in d.current_url
            or "/conferma" in d.current_url
            or "promuovi" in d.current_url)

        # 8. Click Pubblica annuncio (on the anteprima/conferma page)
        pubblica = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable(
                (By.XPATH,
                 "//button[contains(@class,'sbt-button') and "
                 "normalize-space()='Pubblica annuncio']")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});",
                              pubblica)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", pubblica)
        print("[Subito] Clicked Pubblica annuncio — waiting for confirmation…")

        # 8b. Post-publish upsell — skip promotion (two steps)
        self._try_click(driver,
            "//button[normalize-space()='Continua con visibilità minima']", 8)
        self._try_click(driver,
            "//button[contains(@class,'outline') and normalize-space()='Continua']", 8)

        # Wait for post-publish confirmation (various URL patterns)
        WebDriverWait(driver, 20).until(
            lambda d: "promuovi" in d.current_url
            or "/inserito" in d.current_url
            or "adId=" in d.current_url)

        # Extract listing ID from URL
        listing_id = self._extract_uuid(driver.current_url)
        print(f"[Subito] Published — UUID: {listing_id}")

        # 9. Skip upsell screens (if any)
        self._skip_promotions(driver)
        return listing_id

    def update(self, article: dict, driver: Any) -> None:
        raise NotImplementedError("SubitoProvider.update() not yet implemented")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _select_react_option(self, driver, aria_label, keyword):
        """Open a react-select dropdown identified by aria-label and pick an option."""
        combo_input = driver.find_element(
            By.CSS_SELECTOR, f'input[aria-label="{aria_label}"]')
        # The input itself is a zero-size dummy — click the control container instead
        driver.execute_script("""
            var control = arguments[0].closest('[class*="control"]');
            if (control) control.scrollIntoView({block: 'center'});
        """, combo_input)
        time.sleep(0.4)
        control = combo_input.find_element(
            By.XPATH, './ancestor::div[contains(@class, "control")]')
        control.click()
        time.sleep(0.3)
        # ArrowDown ensures the listbox opens
        ActionChains(driver).send_keys(Keys.ARROW_DOWN).perform()
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[role="option"]')))
        # Click matching option by keyword, fallback to first option
        if not driver.execute_script(_JS_CLICK_OPTION, keyword):
            driver.find_element(By.CSS_SELECTOR, '[role="option"]').click()
        time.sleep(0.3)

    @staticmethod
    def _extract_uuid(url: str) -> str:
        m = re.search(r"id:ad:([a-f0-9-]{36})", url)
        if m:
            return m.group(1)
        m = re.search(r"adId=([a-f0-9-]{36})", url)
        return m.group(1) if m else url

    def _skip_promotions(self, driver: Any) -> None:
        """
        Post-publish upsell flow:
          1. Modal "Sconto speciale"       → "Non mi interessa"
          2. Full-page upsell              → "Continua con visibilità minima"
          3. Possible second modal         → "Non mi interessa"
        """
        self._try_click(driver,
            "//button[normalize-space(text())='Non mi interessa']", 4)
        self._try_click(driver,
            "//button[normalize-space(text())='Continua con visibilità minima']", 5)
        self._try_click(driver,
            "//button[normalize-space(text())='Non mi interessa']", 3)
        try:
            WebDriverWait(driver, 8).until(EC.url_contains("/inserito"))
            print("[Subito] Confirmation page — listing is live")
        except Exception:
            print(f"[Subito] Final URL: {driver.current_url}")

    @staticmethod
    def _try_click(driver: Any, xpath: str, timeout: float) -> bool:
        try:
            btn = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].click();", btn)
            return True
        except Exception:
            return False
