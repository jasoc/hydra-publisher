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

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from base import SeleniumProvider

# ── Category map ──────────────────────────────────────────────────────────────
CATEGORY_MAP: dict[str, int] = {
    "arredamento": 14,
    "arredamento e casalinghi": 14,
    "casa e giardino": 14,
    "elettronica": 8,
    "informatica": 8,
    "telefonia": 12,
    "abbigliamento": 25,
    "moda": 25,
    "sport": 32,
    "hobby": 32,
    "libri": 19,
    "musica": 20,
    "videogiochi": 22,
    "auto": 101,
    "moto": 102,
}
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
        category_id = CATEGORY_MAP.get(
                          str(article.get("category", "")).strip().lower(),
                          DEFAULT_CATEGORY)

        # 1. Navigate directly to the insertion form
        driver.get(
            f"https://inserimento.subito.it/"
            f"?category={category_id}"
            f"&subject={urllib.parse.quote(title)}"
            f"&from=vendere"
        )
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "price")))
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
