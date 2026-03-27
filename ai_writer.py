import os
from typing import Any, Dict
from logging import getLogger
from providers.stub_provider import StubProvider

logger = getLogger(__name__)

class AIWriter:
    """Wrapper IA qui charge un provider et génère du texte."""

    def __init__(self, provider_name: str | None = None) -> None:
        self.provider_name = provider_name or os.getenv('AI_PROVIDER', 'stub')
        self.provider = StubProvider()
        logger.info('AIWriter: using provider %s', self.provider_name)

    def generate_content(self, event: Dict[str, Any]) -> str:
        """Génère le contenu textuel pour l'événement via le provider."""
        return self.provider.generate(event)
