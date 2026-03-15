"""
Local Test Selenium provider.

This is a working example of a SeleniumProvider.  It does NOT publish to any
real platform — it simply opens a Chrome window and navigates through a
fictional flow so you can verify that:

  • the browser opens once and stays open across multiple articles
  • login() is called exactly once per session (before the first article)
  • publish() / update() receive the article dict and the live driver
  • Selenium interactions work as expected in your environment

Copy this file and rename it to build your own browser-based provider.
Add any extra pip packages to ../requirements.txt.
"""

import time
from typing import Any

from base import SeleniumProvider


class LocalTestSeleniumProvider(SeleniumProvider):
    """
    Example Selenium provider that uses https://example.com as a stand-in
    for a real marketplace.  Demonstrates the login-once / reuse pattern.
    """

    # ── Login ──────────────────────────────────────────────────────────────

    def login(self, driver: Any) -> None:
        """
        Called once the first time this provider is used in a session.
        Open the platform login page and wait until the user is authenticated.

        Here we simply navigate to example.com to prove the browser opened.
        In a real provider you would:
          1. driver.get("https://yourplatform.com/login")
          2. Wait for the user to type credentials and press Log in, e.g.:
               from selenium.webdriver.support.ui import WebDriverWait
               from selenium.webdriver.support import expected_conditions as EC
               from selenium.webdriver.common.by import By
               WebDriverWait(driver, 300).until(
                   EC.url_contains("dashboard")
               )
        """
        print("[LocalTestSelenium] Opening browser — please 'log in' (press Enter in the app).")
        driver.get("https://example.com")
        # Simulate waiting for the user to interact (real: wait for a post-login URL/element)
        time.sleep(2)
        print("[LocalTestSelenium] Login step complete.")

    # ── Publish ────────────────────────────────────────────────────────────

    def publish(self, article: dict, driver: Any) -> None:
        """
        Publish a new listing.

        Demonstrates how to:
          • navigate to a page
          • locate form elements (here by placeholder attribute as an example)
          • fill in article data and submit

        article dict keys: id, name, description, price, photos, videos,
                           folderPath, category, condition
        """
        print(f"[LocalTestSelenium] Publishing article: {article.get('name')} (id={article.get('id')})")

        # Navigate to the target page (replace with the real "new listing" URL)
        driver.get("https://example.com")

        # Example: locate a form field and fill it in
        # title_field = driver.find_element(By.ID, "listing-title")
        # title_field.clear()
        # title_field.send_keys(article["name"])

        # Simulate the work taking a moment
        time.sleep(1)

        # Example: submit the form
        # submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        # submit_btn.click()
        # WebDriverWait(driver, 30).until(EC.url_contains("success"))

        print(f"[LocalTestSelenium] Published OK: {article.get('name')}")

    # ── Update ─────────────────────────────────────────────────────────────

    def update(self, article: dict, driver: Any) -> None:
        """
        Update an existing listing.

        In a real provider you would:
          1. Navigate to the edit URL for this article (you may need to store
             the platform's listing ID somewhere, e.g. in a sidecar JSON file).
          2. Clear and refill changed fields.
          3. Submit the form.
        """
        print(f"[LocalTestSelenium] Updating article: {article.get('name')} (id={article.get('id')})")

        driver.get("https://example.com")
        time.sleep(1)

        print(f"[LocalTestSelenium] Updated OK: {article.get('name')}")
