"""
Subito.it provider.

Subito.it does not offer a public API, but there is an unofficial Python
wrapper that reverse-engineers the mobile/web API endpoints. This provider
is a stub: fill in the implementation using your chosen library.

Example libraries:
  - https://github.com/amignoli/pysubito   (unofficial, not actively maintained)
  - Custom requests-based wrapper analysing network traffic

Add any required pip package to ../requirements.txt.
"""

from base import Provider


class SubitoProvider(Provider):
    uses_selenium = False

    def __init__(self):
        # TODO: initialise your API client / session here
        # e.g. self.client = SubitoClient(username=..., password=...)
        pass

    def publish(self, article: dict) -> None:
        """
        Publish a new listing on subito.it.

        article keys: id, name, description, price, photos, videos,
                      folderPath, category, condition
        """
        # TODO: implement
        print(f"Publishing article {article['id']} to Subito.it...")
        raise NotImplementedError("SubitoProvider.publish() is not yet implemented")

    def update(self, article: dict) -> None:
        """Update an existing listing on subito.it."""
        # TODO: implement
        raise NotImplementedError("SubitoProvider.update() is not yet implemented")
