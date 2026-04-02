"""
Provider IA Gemini — génération de contenu contextuel pour le simulateur Jira.
Utilise Gemini 2.0 Flash (tier gratuit : 1500 req/jour).
"""
import os
import logging
import random
from typing import Dict
from dotenv import load_dotenv

load_dotenv()

from providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

# Fallback si l'API échoue
FALLBACK_RESPONSES = {
    'add_comment': [
        "Point de suivi : avancement conforme aux attentes, je continue sur cette direction.",
        "Quelques points bloquants identifiés, je reviens avec une proposition.",
        "RAS de mon côté, en attente de retour avant de continuer.",
    ],
    'change_status': [
        "Passage de statut effectué suite à l'avancement du ticket.",
        "Transition validée après vérification des critères d'acceptance.",
    ],
    'create_issue': [
        "Nouveau ticket créé suite à une anomalie détectée.",
        "Création d'une tâche complémentaire identifiée lors de l'analyse.",
    ],
    'default': ["Action effectuée conformément au processus de l'équipe."],
}


class GeminiProvider(BaseProvider):
    """Provider Gemini 2.0 Flash pour la génération de contenu simulé."""

    MODEL = "gemini-2.0-flash"

    def __init__(self) -> None:
        try:
            import google.generativeai as genai
            api_key = os.getenv('GEMINI_API_KEY', '')
            if not api_key:
                raise ValueError("GEMINI_API_KEY manquant dans .env")
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(self.MODEL)
            logger.info("GeminiProvider initialisé avec le modèle %s", self.MODEL)
        except Exception as e:
            logger.error("GeminiProvider : échec d'initialisation — %s", e)
            self._model = None

    def generate(self, event: Dict) -> str:
        """Génère un texte contextuel pour l'événement via Gemini."""
        if self._model is None:
            return self._fallback(event)
        try:
            prompt = self._build_prompt(event)
            response = self._model.generate_content(prompt)
            text = response.text.strip()
            logger.debug("Gemini → %s caractères générés", len(text))
            return text
        except Exception as e:
            logger.warning("Gemini erreur API : %s — utilisation du fallback", e)
            return self._fallback(event)

    def _build_prompt(self, event: Dict) -> str:
        """Construit le prompt contextuel selon le type de scénario."""
        scenario_id  = event.get('scenario_id', '')
        member_name  = event.get('member_name', 'Un membre')
        member_role  = event.get('member_role', 'dev')
        team_id      = event.get('team_id', "l'équipe")
        ticket_key   = event.get('ticket_key', '')
        ticket_sum   = event.get('ticket_summary', '')
        issue_type   = event.get('issue_type', 'Story')
        ctx          = event.get('context', {})
        status_from  = ctx.get('current_status', '')
        status_to    = ctx.get('target_status', '')
        epic_summary = ctx.get('epic_summary', '')
        target_member = ctx.get('target_member_name', '')
        priority     = ctx.get('priority', 'Medium')

        # Contexte commun injecté dans tous les prompts
        base_context = f"""Tu simules {member_name}, {member_role} dans l'équipe "{team_id}".
Ticket concerné : {ticket_key} [{issue_type}] — "{ticket_sum}"
Priorité : {priority}{f' | Epic : "{epic_summary}"' if epic_summary else ''}

RÈGLES ABSOLUES :
- Maximum 3 phrases. Naturel et professionnel, jamais corporate.
- En français. Varie les formulations — évite de commencer par "Je".
- Réponds UNIQUEMENT avec le message, sans introduction, sans guillemets, sans signature.
"""

        # Prompts spécialisés par scénario
        prompts = {
            'mise_a_jour_progression': base_context + """
Action : tu postes une mise à jour de progression sur ce ticket.
Mentionne où tu en es concrètement (ce qui est fait, ce qui reste, un éventuel point d'attention).
""",
            'synthese_epic': base_context + """
Action : tu commentes cette Epic en tant que Lead pour faire un point de suivi.
Parle de la progression globale, d'un risque identifié ou d'une décision à prendre.
""",
            'precision_qa': base_context + f"""
Action : tu es QA et tu laisses un commentaire de revue sur ce ticket ({status_from}).
Mentionne un point de test, une anomalie, ou une validation effectuée.
""",
            'blocage': base_context + f"""
Action : tu passes ce ticket en BLOCKED et tu expliques le blocage.
Sois précis sur la cause (dépendance externe, specs floues, problème technique).
Mentionne ce qui est nécessaire pour débloquer.
""",
            'rejet_review': base_context + f"""
Action : tu retournes ce ticket de IN REVIEW vers IN PROGRESS après ta revue.
Explique brièvement ce qui n'est pas satisfaisant (test manquant, cas non couvert, etc.).
""",
            'demande_clarification_metier': base_context + f"""
Action : tu es DEV et tu interpelles {target_member or 'le BA'} pour une clarification métier.
Pose une question technique précise sur ce ticket — spécifications, comportement attendu, règle de gestion.
""",
            'affinement_backlog': base_context + f"""
Action : tu affines ce ticket lors d'une session de backlog grooming.
Ajoute une précision sur les critères d'acceptance, une contrainte technique, ou une dépendance.
""",
            'relance_lead': base_context + f"""
Action : tu es Lead et ce ticket n'a pas bougé depuis plusieurs jours.
Laisse un message de relance courtois mais direct — demande un point de situation.
""",
            'fragmentation_story': base_context + f"""
Action : tu fragmente cette Story trop complexe en deux parties.
Explique pourquoi la story est trop grande et décris les deux nouvelles sous-parties.
""",
            'cloture_epic': base_context + f"""
Action : tu passes cette Epic en DONE après finalisation des travaux.
Fais un court bilan : ce qui a été livré, les points notables, les enseignements.
""",
            'pret_mise_en_service': base_context + f"""
Action : tu valides et passes ces tickets en DONE avant une mise en service.
Confirme que les validations sont faites et que les tickets sont prêts pour le déploiement.
""",
            'lien_transverse_inter_equipes': base_context + f"""
Action : tu crées un lien "Relates to" entre ce ticket et un ticket d'une autre équipe.
Explique en une phrase pourquoi ces deux tickets sont liés.
""",
        }

        # Prompt pour les transitions avec commentaire optionnel
        if event.get('context', {}).get('transition_comment') and status_from and status_to:
            return base_context + f"""
Action : ce ticket passe de "{status_from}" à "{status_to}".
Laisse un commentaire naturel qui explique ou accompagne ce changement de statut.
"""

        return prompts.get(scenario_id,
               prompts.get(event.get('type', ''), base_context + """
Action : effectue l'action sur ce ticket et laisse un commentaire approprié.
"""))

    def _describe_event_type(self, event_type: str) -> str:
        """Description textuelle d'un type d'événement (utilisé dans certains prompts)."""
        descriptions = {
            'add_comment':    'Commentaire de suivi',
            'change_status':  'Changement de statut',
            'change_assignee':'Réassignation',
            'create_issue':   'Création de ticket',
            'create_subtask': 'Création de sous-tâche',
            'create_link':    'Création de lien',
            'update_field':   'Mise à jour de champ',
            'split_issue':    'Fragmentation de ticket',
        }
        return descriptions.get(event_type, 'Action')

    def _fallback(self, event: Dict) -> str:
        """Retourne une réponse de fallback si Gemini est indisponible."""
        event_type = event.get('type', 'default')
        responses = FALLBACK_RESPONSES.get(event_type,
                    FALLBACK_RESPONSES['default'])
        return random.choice(responses)
