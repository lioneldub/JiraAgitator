import os
import logging
from typing import Dict, Any

from providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
except ImportError:
    genai = None


class GeminiProvider(BaseProvider):
    """Provider Gemini 2.0 Flash."""

    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise EnvironmentError('GEMINI_API_KEY manquant')
        if not genai:
            raise ImportError('google-generativeai non installé')

        genai.configure(api_key=self.api_key)
        self.model = 'gemini-2.0-flash'

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
            response = genai.GenerativeModel(self.model).generate_content(
                prompt=prompt,
                max_output_tokens=150,
                temperature=0.8
            )
            return response.text.strip() if response and getattr(response, 'text', None) else ''
        except Exception as exc:
            logger.error('GeminiProvider erreur: %s', exc)
            return 'Réponse par défaut : progression normale, rendez-vous à la revue.'
