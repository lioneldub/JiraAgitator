import os
from typing import Any, Dict
from logging import getLogger

logger = getLogger(__name__)

class AIWriter:
    """Wrapper IA qui charge dynamiquement le provider selon AI_PROVIDER."""

    def __init__(self, provider_name: str | None = None) -> None:
        self.provider_name = provider_name or os.getenv('AI_PROVIDER', 'stub')
        self.provider = self._load_provider(self.provider_name)
        logger.info("AIWriter: using provider '%s'", self.provider_name)

    def _load_provider(self, name: str):
        if name == 'stub':
            from providers.stub_provider import StubProvider
            return StubProvider()
        elif name == 'gemini':
            from providers.gemini_provider import GeminiProvider
            return GeminiProvider()
        elif name == 'groq':
            from providers.groq_provider import GroqProvider
            return GroqProvider()
        else:
            logger.warning("Provider '%s' inconnu, fallback sur stub", name)
            from providers.stub_provider import StubProvider
            return StubProvider()

    def generate_content(self, event: Dict[str, Any]) -> str:
        """Génère le contenu textuel pour l'événement via le provider."""
        return self.provider.generate(event)

