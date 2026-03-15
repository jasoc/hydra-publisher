"""
Base provider classes for hydra-publisher.

A provider handles publishing/updating articles to a specific marketplace.

Two base classes are available:
  - Provider: for platforms with HTTP APIs (no browser needed)
  - SeleniumProvider: for platforms that require browser automation

Selenium sessions are managed by the server and injected into method calls,
so a single browser window is reused across all articles for a given provider.
"""

from abc import ABC, abstractmethod
from typing import Any


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
