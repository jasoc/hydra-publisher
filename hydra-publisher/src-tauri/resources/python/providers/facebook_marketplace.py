"""
Facebook Marketplace provider.

Automates listing creation on Facebook Marketplace via Selenium.
Uses a persistent Chrome profile so the user can log in manually once
(including TOTP / 2FA); subsequent runs reuse the saved session.
"""

import os
import time
from typing import Any

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from base import SeleniumProvider

CREATE_ITEM_URL = "https://www.facebook.com/marketplace/create/item"


class FacebookMarketplaceProvider(SeleniumProvider):
    """
    Selenium provider for Facebook Marketplace.

    login()          — opens Facebook in the browser for optional manual login
    publish()        — fills and submits the listing form
    """

    # ── Login ──────────────────────────────────────────────────────────────

    def login(self, driver: Any) -> None:
        """Open Facebook in the current Selenium session for manual login."""
        driver.get("https://www.facebook.com/")
        wait_short = WebDriverWait(driver, 3)

        # Accept cookies if banner is shown
        try:
            wait_short.until(
                EC.presence_of_element_located(
                    (By.XPATH, '//div[@role="button"][@aria-label="Allow all cookies"]')
                )
            )
            for btn in driver.find_elements(
                By.XPATH, '//div[@role="button"][@aria-label="Allow all cookies"]'
            ):
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    break
        except Exception:
            pass

        try:
            WebDriverWait(driver, 3).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//div[@role="navigation"]')
                )
            )
            print("[FacebookMarketplace] Session already active.")
        except Exception:
            print("[FacebookMarketplace] Please complete manual login in the opened browser.")

    # ── Publish ────────────────────────────────────────────────────────────

    def publish(self, article: dict, driver: Any) -> None:
        name = article.get("name", "")
        description = article.get("description", "")
        price = article.get("price")
        photos = article.get("photos", [])
        folder_path = article.get("folderPath", "")
        category = article.get("category", "")
        condition = article.get("condition", "")

        # Photos in the manifest are just filenames — resolve to absolute paths
        if folder_path:
            photos = [
                p if os.path.isabs(p) else os.path.join(folder_path, p)
                for p in photos
            ]

        if not name:
            raise ValueError("Article name is required")
        if price is None:
            raise ValueError("Article price is required")

        print(f"[FacebookMarketplace] Publishing: {name}")

        driver.get(CREATE_ITEM_URL)
        wait = WebDriverWait(driver, 10)
        time.sleep(2)  # let React render the form

        # ── Photos ─────────────────────────────────────────────────────
        if photos:
            file_input = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, '//input[@type="file"][@accept]')
                )
            )
            driver.execute_script("arguments[0].style.display = 'block';", file_input)
            file_input.send_keys("\n".join(photos))
            print(f"[FacebookMarketplace] Uploaded {len(photos)} photo(s)")
            time.sleep(1)

        # ── Title ──────────────────────────────────────────────────────
        titolo_input = wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, '//label[.//span[contains(text(), "Titolo")]]//input[@type="text"]')
            )
        )
        titolo_input.clear()
        titolo_input.send_keys(name)
        print(f"[FacebookMarketplace] Title set: {name}")

        # ── Price ──────────────────────────────────────────────────────
        prezzo_input = wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, '//label[.//span[contains(text(), "Prezzo")]]//input[@type="text"]')
            )
        )
        prezzo_input.clear()
        prezzo_input.send_keys(str(int(price)))
        print(f"[FacebookMarketplace] Price set: {price}")

        # ── Category ──────────────────────────────────────────────────
        if category:
            self._select_dropdown(driver, wait, "Categoria", category)

        # ── Condition ─────────────────────────────────────────────────
        if condition:
            self._select_dropdown(driver, wait, "Condizione", condition)

        # ── Description ───────────────────────────────────────────────
        if description:
            try:
                desc_input = wait.until(
                    EC.visibility_of_element_located(
                        (By.XPATH,
                         '//label[.//span[contains(text(), "Descrizione")]]//textarea')
                    )
                )
                desc_input.clear()
                desc_input.send_keys(description)
                print("[FacebookMarketplace] Description set")
            except Exception:
                print("[FacebookMarketplace] Description field not found, skipping")

        # ── Avanti (Next) ─────────────────────────────────────────────
        try:
            avanti_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     '//div[@role="button" and '
                     '(.//span[text()="Avanti"] or .//span[text()="Next"])]')
                )
            )
            driver.execute_script("arguments[0].click();", avanti_btn)
            print("[FacebookMarketplace] Clicked 'Avanti'")
            time.sleep(2)
        except Exception as exc:
            print(f"[FacebookMarketplace] 'Avanti' button not found: {exc}")

        # ── Pubblica (Publish) ────────────────────────────────────────
        try:
            pubblica_btn = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     '//div[@role="button" and '
                     '(.//span[text()="Pubblica"] or .//span[text()="Publish"])]')
                )
            )
            driver.execute_script("arguments[0].click();", pubblica_btn)
            print(f"[FacebookMarketplace] Published: {name}")
            time.sleep(2)
        except Exception as exc:
            raise RuntimeError(
                f"Could not click 'Pubblica': {exc}"
            )

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _select_dropdown(driver, wait, label_text: str, option_text: str) -> None:
        """
        Open a Facebook combobox identified by *label_text* and click the
        option whose text contains *option_text*.

        Uses the universal XPath strategy:
            //*[text()[contains(., 'option_text')]]
        """
        combobox = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH,
                 f'//label[@role="combobox"]'
                 f'[.//span[contains(text(), "{label_text}")]]')
            )
        )
        driver.execute_script("arguments[0].click();", combobox)
        time.sleep(1.2)

        xpath = f'//*[text()[contains(., "{option_text}")]]'
        wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        candidates = driver.find_elements(By.XPATH, xpath)

        for el in candidates:
            try:
                driver.execute_script("arguments[0].click();", el)
                print(f"[FacebookMarketplace] Selected '{option_text}' for '{label_text}'")
                return
            except Exception:
                continue

        raise RuntimeError(
            f"Option '{option_text}' not found in DOM after opening '{label_text}'"
        )
