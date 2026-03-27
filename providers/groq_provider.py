import os
import logging
from typing import Dict, Any

from providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

try:
    from groq import Groq
except ImportError:
    Groq = None


class GroqProvider(BaseProvider):
    """Provider Groq / Llama 3.3"""

    def __init__(self):
        self.api_key = os.getenv('GROQ_API_KEY')
        if not self.api_key:
            raise EnvironmentError('GROQ_API_KEY manquant')
        if not Groq:
            raise ImportError('groq non installé')

        self.client = Groq(api_key=self.api_key)

    def _build_prompt(self, event: Dict[str, Any]) -> str:
        member_name = event.get('member_name', 'Un membre')
        member_role = event.get('member_role', 'dev')
        team_id = event.get('team_id', 'l\'équipe')
        ticket_key = event.get('ticket_key')
        ticket_summary = event.get('ticket_summary', 'ticket')
        current_status = event.get('context', {}).get('current_status', 'Non défini')
        action = self._describe_event_type(event.get('type', 'comment'))

        if ticket_key:
            return (
                f"Tu simules {member_name}, {member_role} dans l'équipe Scrum '{team_id}'.\n"
                f"Tu travailles sur le ticket '{ticket_key} — {ticket_summary}' (statut actuel : {current_status}).\n"
                f"Action demandée : {action}\n\n"
                "Génère un message court (2-4 phrases maximum) en français, naturel et professionnel, "
                "comme si tu étais vraiment ce développeur dans son outil de ticketing. "
                "Ne commence pas par 'Je' — varie les formulations. Réponds uniquement avec le message, sans introduction ni explication."
            )
        return (
            f"Tu simules {member_name}, {member_role} dans l'équipe Scrum '{team_id}'.\n"
            f"Action : {action}\n\n"
            "Génère un message court (2-4 phrases maximum) en français, naturel et professionnel, "
            "comme si tu étais vraiment ce développeur dans son outil de ticketing. "
            "Ne commence pas par 'Je' — varie les formulations. Réponds uniquement avec le message, sans introduction ni explication."
        )

    def _describe_event_type(self, event_type: str) -> str:
        descriptions = {
            'add_comment': 'Ajouter un commentaire de suivi sur ce ticket',
            'change_status': 'Signaler l\'avancement ou la complétion du ticket',
            'block_ticket': 'Expliquer un blocage technique ou organisationnel',
            'change_assignee': 'Justifier brièvement la réassignation',
            'set_absence': 'Annoncer une absence et le transfert des tickets',
            'return_from_absence': 'Signaler le retour et la reprise des activités',
            'add_subtask': 'Décrire la sous-tâche créée et son périmètre',
        }
        return descriptions.get(event_type, 'Commenter ce ticket')

    def generate(self, event: Dict[str, Any]) -> str:
        prompt = self._build_prompt(event)
        try:
            response = self.client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=150,
                temperature=0.8
            )
            content = (response.choices[0].message.content if response and getattr(response, 'choices', None) else '')
            return content.strip() if isinstance(content, str) else ''
        except Exception as exc:
            logger.error('GroqProvider erreur: %s', exc)
            return 'Réponse par défaut : progression normale, rendez-vous à la revue.'
