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

# App category (from categories.model.ts) → Facebook Marketplace dropdown label.
# Facebook has ~25 categories; the _select_dropdown helper uses contains(text())
# so partial matches work.
_FB_CATEGORY_MAP: dict[str, str] = {
    # Casa e cucina / Ufficio e casa
    "Arredamento":                  "Arredamento",
    "Elettrodomestici cucina":      "Elettrodomestici",
    "Pentole e padelle":            "Articoli per la casa",
    "Utensili cucina":              "Articoli per la casa",
    "Stoviglie":                    "Articoli per la casa",
    "Biancheria letto":             "Articoli per la casa",
    "Tende e tapparelle":           "Articoli per la casa",
    "Tappeti":                      "Articoli per la casa",
    "Candele e profumi casa":       "Articoli per la casa",
    "Illuminazione":                "Articoli per la casa",
    "Cornici":                      "Articoli per la casa",
    "Specchi":                      "Articoli per la casa",
    "Vasi":                         "Articoli per la casa",
    "Decorazioni parete":           "Articoli per la casa",
    "Materiale ufficio":            "Articoli per la casa",
    "Attrezzi e bricolage":         "Attrezzi",
    "Giardino":                     "Giardino",
    "Animali":                      "Articoli per animali",
    # Abbigliamento donna
    "Vestiti donna":                "Abbigliamento e scarpe da donna",
    "Giacche e cappotti donna":     "Abbigliamento e scarpe da donna",
    "Maglioni e pullover donna":    "Abbigliamento e scarpe da donna",
    "Abiti donna":                  "Abbigliamento e scarpe da donna",
    "Gonne":                        "Abbigliamento e scarpe da donna",
    "Top e t-shirt donna":          "Abbigliamento e scarpe da donna",
    "Jeans donna":                  "Abbigliamento e scarpe da donna",
    "Pantaloni donna":              "Abbigliamento e scarpe da donna",
    "Pantaloncini donna":           "Abbigliamento e scarpe da donna",
    "Costumi da bagno donna":       "Abbigliamento e scarpe da donna",
    "Lingerie e pigiami":           "Abbigliamento e scarpe da donna",
    "Abbigliamento sportivo donna": "Abbigliamento e scarpe da donna",
    "Scarpe donna":                 "Abbigliamento e scarpe da donna",
    "Stivali donna":                "Abbigliamento e scarpe da donna",
    "Sandali donna":                "Abbigliamento e scarpe da donna",
    "Tacchi":                       "Abbigliamento e scarpe da donna",
    "Sneakers donna":               "Abbigliamento e scarpe da donna",
    "Borse":                        "Borse e valigie",
    "Zaini donna":                  "Borse e valigie",
    "Pochette":                     "Borse e valigie",
    "Portafogli donna":             "Borse e valigie",
    "Cinture donna":                "Gioielli e accessori",
    "Cappelli donna":               "Gioielli e accessori",
    "Gioielli donna":               "Gioielli e accessori",
    "Sciarpe e scialli donna":      "Gioielli e accessori",
    "Occhiali da sole donna":       "Gioielli e accessori",
    "Orologi donna":                "Gioielli e accessori",
    # Bellezza
    "Make-up":                      "Salute e bellezza",
    "Profumi":                      "Salute e bellezza",
    "Cura del viso":                "Salute e bellezza",
    "Cura del corpo":               "Salute e bellezza",
    # Abbigliamento uomo
    "Vestiti uomo":                 "Abbigliamento e scarpe da uomo",
    "Giacche e cappotti uomo":      "Abbigliamento e scarpe da uomo",
    "Camicie uomo":                 "Abbigliamento e scarpe da uomo",
    "T-shirt uomo":                 "Abbigliamento e scarpe da uomo",
    "Maglioni e pullover uomo":     "Abbigliamento e scarpe da uomo",
    "Completi e blazer uomo":       "Abbigliamento e scarpe da uomo",
    "Pantaloni uomo":               "Abbigliamento e scarpe da uomo",
    "Jeans uomo":                   "Abbigliamento e scarpe da uomo",
    "Pantaloncini uomo":            "Abbigliamento e scarpe da uomo",
    "Costumi da bagno uomo":        "Abbigliamento e scarpe da uomo",
    "Abbigliamento sportivo uomo":  "Abbigliamento e scarpe da uomo",
    "Scarpe uomo":                  "Abbigliamento e scarpe da uomo",
    "Stivali uomo":                 "Abbigliamento e scarpe da uomo",
    "Sneakers uomo":                "Abbigliamento e scarpe da uomo",
    "Scarpe formali":               "Abbigliamento e scarpe da uomo",
    "Cinture uomo":                 "Gioielli e accessori",
    "Cappelli uomo":                "Gioielli e accessori",
    "Gioielli uomo":                "Gioielli e accessori",
    "Cravatte e papillon":          "Gioielli e accessori",
    "Orologi uomo":                 "Gioielli e accessori",
    "Occhiali da sole uomo":        "Gioielli e accessori",
    # Bambini
    "Abbigliamento bambina":        "Neonati e bambini",
    "Abbigliamento bambino":        "Neonati e bambini",
    "Scarpe bambini":               "Neonati e bambini",
    "Giocattoli":                   "Giocattoli e videogiochi",
    "Peluche":                      "Giocattoli e videogiochi",
    "Costruzioni":                  "Giocattoli e videogiochi",
    "Bambole":                      "Giocattoli e videogiochi",
    "Passeggini e carrozzine":      "Neonati e bambini",
    "Seggiolini auto":              "Neonati e bambini",
    "Arredamento bambini":          "Neonati e bambini",
    # Elettronica
    "Videogiochi e console":        "Videogiochi",
    "Console":                      "Videogiochi",
    "Computer portatili":           "Elettronica e computer",
    "Computer desktop":             "Elettronica e computer",
    "Componenti PC":                "Elettronica e computer",
    "Tastiere":                     "Elettronica e computer",
    "Mouse":                        "Elettronica e computer",
    "Monitor":                      "Elettronica e computer",
    "Stampanti":                    "Elettronica e computer",
    "Smartphone":                   "Cellulari",
    "Accessori telefono":           "Cellulari",
    "Cuffie e auricolari":          "Elettronica e computer",
    "Altoparlanti e speaker":       "Elettronica e computer",
    "Audio e hi-fi":                "Elettronica e computer",
    "Fotocamere":                   "Elettronica e computer",
    "Obiettivi":                    "Elettronica e computer",
    "Tablet":                       "Elettronica e computer",
    "E-reader":                     "Elettronica e computer",
    "Televisori":                   "Elettronica e computer",
    "Proiettori":                   "Elettronica e computer",
    "Smartwatch":                   "Elettronica e computer",
    "Fitness tracker":              "Elettronica e computer",
    "Caricabatterie e power bank":  "Elettronica e computer",
    "Cavi e adattatori":            "Elettronica e computer",
    # Intrattenimento
    "Libri":                        "Libri, film e musica",
    "Narrativa":                    "Libri, film e musica",
    "Saggistica":                   "Libri, film e musica",
    "Fumetti e manga":              "Libri, film e musica",
    "Riviste":                      "Libri, film e musica",
    "Musica":                       "Libri, film e musica",
    "Vinile":                       "Libri, film e musica",
    "CD":                           "Libri, film e musica",
    "DVD e Blu-ray":                "Libri, film e musica",
    # Hobby e collezionismo
    "Carte collezionabili":         "Articoli d'antiquariato e da collezione",
    "Giochi da tavolo":             "Giocattoli e videogiochi",
    "Puzzle":                       "Giocattoli e videogiochi",
    "Monete e banconote":           "Articoli d'antiquariato e da collezione",
    "Francobolli":                  "Articoli d'antiquariato e da collezione",
    "Strumenti musicali":           "Strumenti musicali",
    "Chitarre":                     "Strumenti musicali",
    "Arte e artigianato":           "Arte e artigianato",
    # Sport
    "Ciclismo":                     "Biciclette",
    "Fitness e palestra":           "Sport e attività all'aperto",
    "Corsa":                        "Sport e attività all'aperto",
    "Yoga e pilates":               "Sport e attività all'aperto",
    "Campeggio":                    "Sport e attività all'aperto",
    "Arrampicata":                  "Sport e attività all'aperto",
    "Pesca":                        "Sport e attività all'aperto",
    "Nuoto":                        "Sport e attività all'aperto",
    "Surf e SUP":                   "Sport e attività all'aperto",
    "Calcio":                       "Sport e attività all'aperto",
    "Basket":                       "Sport e attività all'aperto",
    "Pallavolo":                    "Sport e attività all'aperto",
    "Tennis":                       "Sport e attività all'aperto",
    "Padel":                        "Sport e attività all'aperto",
    "Golf":                         "Sport e attività all'aperto",
    "Equitazione":                  "Sport e attività all'aperto",
    "Skateboard":                   "Sport e attività all'aperto",
    "Boxe e arti marziali":         "Sport e attività all'aperto",
    "Sci":                          "Sport e attività all'aperto",
    "Snowboard":                    "Sport e attività all'aperto",
    "Pattinaggio":                  "Sport e attività all'aperto",
    # Griffati
    "Articoli griffati":            "Abbigliamento e scarpe da donna",
    "Borse griffate":               "Borse e valigie",
    "Scarpe griffate":              "Abbigliamento e scarpe da donna",
    # Veicoli e altro
    "Auto":                         "Veicoli",
    "Moto":                         "Veicoli",
    "Ricambi auto":                 "Ricambi auto",
}


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
            fb_cat = _FB_CATEGORY_MAP.get(category, category)
            self._select_dropdown(driver, wait, "Categoria", fb_cat)

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
