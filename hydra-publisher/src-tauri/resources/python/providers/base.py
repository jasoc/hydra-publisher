"""
Base provider classes for hydra-publisher.

A provider handles publishing/updating articles to a specific marketplace.

Three base classes are available:
  - Provider: for platforms with HTTP APIs (no browser needed)
  - SeleniumProvider: for platforms that require browser automation
  - FormFiller: helper that reads a YAML selector config and fills a form with
    Selenium — use this to avoid hardcoding selectors inside provider code.

Selenium sessions are managed by the server and injected into method calls,
so a single browser window is reused across all articles for a given provider.

── FormFiller YAML format ────────────────────────────────────────────────────

  publish_url: "https://www.example.com/items/new"

  fields:
    - id: title
      article_key: name          # key in the article dict passed to publish()
      type: text                 # text | textarea | file
      xpath: '//input[@name="title"]'
      # css: 'input[data-testid="title-input"]'   # alternative to xpath

    - id: photos
      article_key: photos        # list of absolute file paths
      type: file
      xpath: '//input[@type="file"]'

  buttons:
    - id: next
      xpath: '//button[contains(., "Avanti")]'
      wait_after: 1.5            # seconds to wait after click (default 1)

    - id: submit
      xpath: '//button[contains(., "Carica")]'
      wait_after: 2

── Usage ─────────────────────────────────────────────────────────────────────

  class MyProvider(SeleniumProvider):
      _filler = FormFiller(os.path.join(os.path.dirname(__file__), "selectors", "mysite.yaml"))

      def publish(self, article, driver):
          driver.get(self._filler.publish_url)
          time.sleep(2)
          self._filler.fill(article, driver)
"""

import os
import time
from abc import ABC, abstractmethod
from typing import Any

import yaml
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ── FormFiller ────────────────────────────────────────────────────────────────

class FormFiller:
    """
    Reads a YAML selector config and fills a marketplace form using Selenium.

    Separates selector maintenance (YAML) from provider logic (Python).
    When a site restyling breaks a selector, update the YAML — no Python changes needed.
    """

    def __init__(self, yaml_path: str) -> None:
        with open(yaml_path, encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        self.publish_url: str = config.get("publish_url", "")
        self._fields: list[dict] = config.get("fields", [])
        self._buttons: list[dict] = config.get("buttons", [])

    def fill(self, article: dict, driver: Any, timeout: int = 15) -> None:
        """
        Fill all form fields defined in the YAML using values from *article*,
        then click all buttons in order.

        article dict keys: id, name, description, price, photos, folderPath,
                           category, condition  (mirrors the Rust Article struct)
        """
        wait = WebDriverWait(driver, timeout)

        for field in self._fields:
            article_key = field.get("article_key")
            value = article.get(article_key) if article_key else None
            if value is None or value == "" or value == []:
                continue

            field_id = field.get("id", article_key)
            field_type = field.get("type", "text")

            try:
                el = self._locate(wait, field)
            except Exception as exc:
                print(f"[FormFiller] Field '{field_id}' not found, skipping: {exc}")
                continue

            if field_type == "file":
                paths = value if isinstance(value, list) else [value]
                # resolve relative paths using folderPath if present
                folder = article.get("folderPath", "")
                if folder:
                    paths = [p if os.path.isabs(p) else os.path.join(folder, p) for p in paths]
                driver.execute_script("arguments[0].style.display='block';", el)
                el.send_keys("\n".join(paths))
                print(f"[FormFiller] '{field_id}': uploaded {len(paths)} file(s)")
                time.sleep(0.5)

            elif field_type in ("text", "textarea"):
                el.clear()
                el.send_keys(str(int(value)) if field_type == "text" and isinstance(value, float) else str(value))
                print(f"[FormFiller] '{field_id}': set to '{str(value)[:40]}'")

        for btn in self._buttons:
            btn_id = btn.get("id", "button")
            wait_after = float(btn.get("wait_after", 1))
            try:
                el = self._locate(wait, btn)
                driver.execute_script("arguments[0].click();", el)
                print(f"[FormFiller] Clicked '{btn_id}'")
                time.sleep(wait_after)
            except Exception as exc:
                raise RuntimeError(f"[FormFiller] Could not click '{btn_id}': {exc}") from exc

    @staticmethod
    def _locate(wait: WebDriverWait, cfg: dict):
        """Find an element using xpath or css from the field/button config."""
        if "xpath" in cfg:
            return wait.until(EC.presence_of_element_located((By.XPATH, cfg["xpath"])))
        if "css" in cfg:
            return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, cfg["css"])))
        raise ValueError(f"No locator (xpath/css) in config: {cfg}")


class Provider(ABC):
    """
    Base class for HTTP-based providers (no Selenium).
    Override publish() and optionally update().
    """

    uses_selenium: bool = False

    @abstractmethod
    def publish(self, article: dict) -> None:
        """
        Publish a new listing for the given article.

        article dict keys (mirrors the Rust Article struct, camelCase):
          id, name, description, price, photos, videos, folderPath,
          category, condition
        """
        ...

    def update(self, article: dict) -> None:
        """
        Update an existing listing. Default raises NotImplementedError.
        Override this if the platform supports updating listings.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support update")


class SeleniumProvider(ABC):
    """
    Base class for browser-based providers.
    The server manages one WebDriver instance per provider subclass.
    On the first call the browser is opened and login() is invoked;
    subsequent calls reuse the same driver instance without re-logging in.

    Override login(), publish(), and optionally update().
    """

    uses_selenium: bool = True

    def login(self, driver: Any) -> None:
        """
        Called once after the browser opens, before the first publish/update.
        Open the login page, let the user log in manually, then return
        (e.g. wait for a post-login URL or element before returning).

        The default implementation does nothing (useful for platforms where
        the user is already logged in via a saved session/cookie).
        """
        pass

    @abstractmethod
    def publish(self, article: dict, driver: Any) -> None:
        """
        Publish a new listing using the already-authenticated browser.
        driver is the active selenium.webdriver.Chrome instance.
        """
        ...

    def update(self, article: dict, driver: Any) -> None:
        """
        Update an existing listing. Default raises NotImplementedError.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support update")

    def start_login(self, body: dict, driver: Any) -> dict:
        """
        Two-step login, step 1: send credentials, return status.
        Default raises NotImplementedError.
        Override this in providers that need automated login (e.g. Facebook).
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support start_login")

    def confirm_login(self, driver: Any) -> dict:
        """
        Two-step login, step 2: confirm login after user interaction (e.g. TOTP).
        Default raises NotImplementedError.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support confirm_login")
