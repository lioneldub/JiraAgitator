from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseProvider(ABC):
    """Interface commune pour tous les providers IA."""

    @abstractmethod
    def generate(self, event: Dict[str, Any]) -> str:
        """Génère un texte à partir d'un événement."""
        ...
