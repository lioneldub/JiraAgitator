import random
from typing import Dict

STUB_RESPONSES = {
    'add_comment': [
        "Point de suivi : j'ai avancé sur la partie backend, les tests unitaires passent. Je continue demain sur l'intégration.",
        "RAS de mon côté, en attente du retour de l'équipe QA avant de passer en review.",
        "Petite complication sur la config Docker, je creuse ça cet après-midi."
    ],
    'change_status': [
        "Ticket déplacé en In Review — prêt pour la relecture.",
        "Passage en In Progress, je prends ce sujet.",
        "Ticket terminé, déployé en staging."
    ],
    'block_ticket': [
        "Ticket bloqué : dépendance non résolue côté API externe, en attente de réponse du fournisseur.",
        "Bloqué en attente de clarification des specs — j'ai pingé le PO.",
        "Blocage technique : la migration de base de données échoue sur l'environnement de test."
    ],
    'change_assignee': [
        "Réassigné suite à rééquilibrage de la charge.",
        "Je reprends ce ticket, l'ancien assignee est surchargé."
    ],
    'set_absence': [
        "Je serai absent jusqu'à nouvel ordre. Mes tickets sont réassignés.",
        "Absence imprévue — tickets transférés à l'équipe."
    ],
    'return_from_absence': [
        "De retour, je reprends mes activités normalement."
    ],
    'add_subtask': [
        "Création d'une sous-tâche pour découper le travail restant."
    ]
}

class StubProvider:
    """Provider stub pour génération de contenu IA de test."""

    def generate(self, event: Dict) -> str:
        """Retourne un texte aléatoire adapté au type d'événement."""
        responses = STUB_RESPONSES.get(event.get('type'), [])
        if not responses:
            return 'Aucun contenu stub disponible pour ce type.'
        return random.choice(responses)
