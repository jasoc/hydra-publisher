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

from selenium.common.exceptions import TimeoutException
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
    "Computer portatili": 8,
    "Computer desktop": 8,
    "Componenti PC": 8,
    "Tastiere": 8,
    "Mouse": 8,
    "Monitor": 8,
    "Stampanti": 8,
    "Cuffie e auricolari": 8,
    "Altoparlanti e speaker": 8,
    "Audio e hi-fi": 8,
    "Fotocamere": 8,
    "Obiettivi": 8,
    "Tablet": 8,
    "E-reader": 8,
    "Televisori": 8,
    "Proiettori": 8,
    "Smartwatch": 8,
    "Fitness tracker": 8,
    "Caricabatterie e power bank": 8,
    "Cavi e adattatori": 8,
    # Telefonia
    "Smartphone": 12,
    "Accessori telefono": 12,
    # Abbigliamento (donna + uomo + bambini generico)
    "Vestiti donna": 25,
    "Giacche e cappotti donna": 25,
    "Maglioni e pullover donna": 25,
    "Abiti donna": 25,
    "Gonne": 25,
    "Top e t-shirt donna": 25,
    "Jeans donna": 25,
    "Pantaloni donna": 25,
    "Pantaloncini donna": 25,
    "Costumi da bagno donna": 25,
    "Lingerie e pigiami": 25,
    "Abbigliamento sportivo donna": 25,
    "Scarpe donna": 25,
    "Stivali donna": 25,
    "Sandali donna": 25,
    "Tacchi": 25,
    "Sneakers donna": 25,
    "Borse": 25,
    "Zaini donna": 25,
    "Pochette": 25,
    "Portafogli donna": 25,
    "Cinture donna": 25,
    "Cappelli donna": 25,
    "Gioielli donna": 25,
    "Sciarpe e scialli donna": 25,
    "Occhiali da sole donna": 25,
    "Orologi donna": 25,
    "Vestiti uomo": 25,
    "Giacche e cappotti uomo": 25,
    "Camicie uomo": 25,
    "T-shirt uomo": 25,
    "Maglioni e pullover uomo": 25,
    "Completi e blazer uomo": 25,
    "Pantaloni uomo": 25,
    "Jeans uomo": 25,
    "Pantaloncini uomo": 25,
    "Costumi da bagno uomo": 25,
    "Abbigliamento sportivo uomo": 25,
    "Scarpe uomo": 25,
    "Stivali uomo": 25,
    "Sneakers uomo": 25,
    "Scarpe formali": 25,
    "Cinture uomo": 25,
    "Cappelli uomo": 25,
    "Gioielli uomo": 25,
    "Cravatte e papillon": 25,
    "Orologi uomo": 25,
    "Occhiali da sole uomo": 25,
    "Abbigliamento bambina": 25,
    "Abbigliamento bambino": 25,
    "Scarpe bambini": 25,
    "Articoli griffati": 25,
    "Borse griffate": 25,
    "Scarpe griffate": 25,
    # Bellezza
    "Make-up": 25,
    "Profumi": 25,
    "Cura del viso": 25,
    "Cura del corpo": 25,
    # Bambini (non-abbigliamento)
    "Giocattoli": 14,
    "Peluche": 14,
    "Costruzioni": 14,
    "Bambole": 14,
    "Passeggini e carrozzine": 14,
    "Seggiolini auto": 14,
    "Arredamento bambini": 14,
    # Sport
    "Ciclismo": 32,
    "Fitness e palestra": 32,
    "Corsa": 32,
    "Yoga e pilates": 32,
    "Campeggio": 32,
    "Arrampicata": 32,
    "Pesca": 32,
    "Nuoto": 32,
    "Surf e SUP": 32,
    "Calcio": 32,
    "Basket": 32,
    "Pallavolo": 32,
    "Tennis": 32,
    "Padel": 32,
    "Golf": 32,
    "Equitazione": 32,
    "Skateboard": 32,
    "Boxe e arti marziali": 32,
    "Sci": 32,
    "Snowboard": 32,
    "Pattinaggio": 32,
    # Hobby e collezionismo
    "Carte collezionabili": 32,
    "Giochi da tavolo": 32,
    "Puzzle": 32,
    "Monete e banconote": 32,
    "Francobolli": 32,
    "Arte e artigianato": 32,
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

# Async: set Comune input, wait for AJAX options, click best match
_JS_SET_COMUNE = """
return (async function(city) {
  var el = document.getElementById('location');
  if (!el) return 'NOT FOUND';
  var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(el, city);
  el.dispatchEvent(new Event('input',  {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  el.focus();
  for (var i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 100));
    var opts = document.querySelectorAll('[role="option"]');
    if (opts.length > 0) {
      var hit = Array.from(opts).find(
        o => o.textContent.toLowerCase().includes(city.toLowerCase()));
      (hit || opts[0]).click();
      return 'clicked: ' + (hit || opts[0]).textContent.trim().substring(0, 40);
    }
  }
  return 'timeout';
})(arguments[0]);
"""

# Click Condizione option by keyword after ArrowDown opens the listbox
_JS_CLICK_CONDITION = """
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

    DEFAULT_CITY  = os.environ.get("SUBITO_DEFAULT_CITY",  "Milano")
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

        # 4. Condizione — real click required to open React-Select,
        #    then ArrowDown, then JS poll + click
        cond_el = driver.find_element(By.CSS_SELECTOR, '[aria-label="Condizione"]')
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", cond_el)
        cond_el.click()                     # real CDP click — JS .click() does NOT work
        cond_el.send_keys(Keys.ARROW_DOWN)  # ensures dropdown opens
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[role="option"]')))
        keyword = condition.split(" - ")[0]
        if not driver.execute_script(_JS_CLICK_CONDITION, keyword):
            driver.find_element(By.CSS_SELECTOR, '[role="option"]').click()

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

        # 6. Comune (AJAX autocomplete) + Phone — one JS call each
        result = driver.execute_script(_JS_SET_COMUNE, city)
        print(f"[Subito] Comune: {result}")
        driver.execute_script(_JS_REACT_SET,
                              driver.find_element(By.ID, "phone"),
                              phone)

        # 7. Click Continua → anteprima page
        continua = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[normalize-space(text())='Continua']")))
        driver.execute_script("arguments[0].click();", continua)
        WebDriverWait(driver, 15).until(EC.url_contains("/anteprima"))

        # 8. Click Pubblica annuncio
        pubblica = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[normalize-space(text())='Pubblica annuncio']")))
        driver.execute_script("arguments[0].click();", pubblica)
        WebDriverWait(driver, 15).until(EC.url_contains("promuovi-form"))

        # Extract UUID from URL before upsell pages change it
        listing_id = self._extract_uuid(driver.current_url)
        print(f"[Subito] Published — UUID: {listing_id}")

        # 9. Skip upsell screens
        self._skip_promotions(driver)
        return listing_id

    def update(self, article: dict, driver: Any) -> None:
        raise NotImplementedError("SubitoProvider.update() not yet implemented")

    # ── helpers ───────────────────────────────────────────────────────────────

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
