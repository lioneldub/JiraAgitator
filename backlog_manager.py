"""
Gestionnaire d'équilibre du backlog.
Crée automatiquement des tickets TO DO et des Epics si le stock est insuffisant.
"""
import os
import random
import logging
from dotenv import load_dotenv

load_dotenv()

from state_manager import StateManager
from jira_client import JiraClient
from ai_writer import AIWriter

logger = logging.getLogger(__name__)

# Seuils configurables via .env
def get_min_todo_tickets():
    return int(os.getenv('MIN_TODO_TICKETS', '10'))

def get_min_active_epics():
    return int(os.getenv('MIN_ACTIVE_EPICS', '10'))

# Summaries de secours si le provider IA échoue
FALLBACK_STORIES = [
    "Amélioration de l'expérience utilisateur sur le tableau de bord",
    "Mise en place des alertes de monitoring sur les APIs critiques",
    "Refactoring du module de gestion des permissions",
    "Documentation technique des composants principaux",
    "Optimisation du temps de chargement des pages lourdes",
    "Revue et mise à jour des dépendances de sécurité",
    "Implémentation du cache sur les endpoints à forte charge",
    "Correction des warnings de lint accumulés",
    "Ajout des tests d'intégration manquants",
    "Mise à jour du runbook de production",
    "Analyse des métriques de performance du mois",
    "Nettoyage des données obsolètes en base",
]

FALLBACK_EPICS = [
    "Modernisation de l'interface utilisateur",
    "Amélioration de la résilience système",
    "Programme de réduction de la dette technique",
    "Initiative qualité et couverture de tests",
    "Optimisation des coûts d'infrastructure",
    "Sécurisation des accès et des données",
    "Automatisation des processus manuels récurrents",
    "Migration vers l'architecture micro-services",
    "Amélioration de l'observabilité et du monitoring",
    "Programme d'onboarding et de documentation",
]


def check_and_replenish(project_keys: list[str],
                         jira_client: JiraClient,
                         state_manager: StateManager,
                         ai_writer: AIWriter,
                         teams_config: dict,
                         dry_run: bool = False) -> dict:
    """
    Vérifie les seuils et crée les tickets manquants.
    Retourne un résumé des créations effectuées.
    """
    state = state_manager.load()
    tickets = state.get('tickets', {})
    members = state.get('members', {})

    # Compter les tickets TO DO par projet
    todo_by_project: dict[str, int] = {k: 0 for k in project_keys}
    epics_by_project: dict[str, int] = {k: 0 for k in project_keys}

    for ticket in tickets.values():
        key_prefix = ticket['key'].split('-')[0]
        if key_prefix not in todo_by_project:
            continue
        if ticket.get('status_category') == 'TO DO':
            todo_by_project[key_prefix] += 1
        if (ticket.get('issue_type') == 'Epic'
                and ticket.get('status_category') != 'DONE'):
            epics_by_project[key_prefix] += 1

    created_stories = 0
    created_epics   = 0

    # Leads disponibles pour assigner les nouveaux tickets
    leads = [mid for mid, data in members.items()
             if data.get('role', '').lower() == 'lead'
             and data.get('availability') == 'available']
    default_lead = leads[0] if leads else None

    for project_key in project_keys:
        # Trouver l'équipe du projet
        team_id = _find_team_for_project(project_key, teams_config)
        lead_id = _find_lead_for_team(team_id, members) or default_lead

        # 1. Créer des Epics si nécessaire
        epics_needed = max(0, get_min_active_epics() - epics_by_project[project_key])
        new_epic_keys = []  # Collecter les clés des nouvelles Epics
        for i in range(epics_needed):
            summary = random.choice(FALLBACK_EPICS)
            account_id = members.get(lead_id, {}).get('jira_account_id', '') if lead_id else ''
            fields = {
                'project': {'key': project_key},
                'summary': summary,
                'issuetype': {'name': 'Epic'},
                'priority': {'name': 'Medium'},
            }
            if account_id:
                fields['assignee'] = {'accountId': account_id}
            result = jira_client.create_issue(fields)
            if result.get('key') or dry_run:
                epic_key = result.get('key') or f"{project_key}-{len(tickets) + created_epics + i + 1}"
                new_epic_keys.append(epic_key)
                created_epics += 1
                logger.info(
                    "[BACKLOG] Epic créée dans %s : '%s'",
                    project_key, summary
                )

        # 2. Créer des Stories TO DO si nécessaire
        # Récupérer les Epics actives pour rattacher les nouvelles Stories
        active_epics = [
            k for k, t in tickets.items()
            if t.get('issue_type') == 'Epic'
            and t.get('status_category') != 'DONE'
            and k.startswith(project_key + '-')
        ] + new_epic_keys  # Ajouter les nouvelles Epics créées

        stories_needed = max(0, get_min_todo_tickets() - todo_by_project[project_key])
        for i in range(stories_needed):
            summary = random.choice(FALLBACK_STORIES)
            # 80% des Stories rattachées à une Epic
            epic_key = None
            if active_epics and random.random() < 0.80:
                epic_key = random.choice(active_epics)

            fields = {
                'project': {'key': project_key},
                'summary': summary,
                'issuetype': {'name': 'Story'},
                'priority': {'name': random.choice(['Low', 'Medium', 'High'])},
            }
            if epic_key:
                fields['parent'] = {'key': epic_key}

            result = jira_client.create_issue(fields)
            if result.get('key') or dry_run:
                created_stories += 1
                logger.info(
                    "[BACKLOG] Story TO DO créée dans %s%s : '%s'",
                    project_key,
                    f" (Epic: {epic_key})" if epic_key else "",
                    summary
                )

    summary_result = {
        'epics_created': created_epics,
        'stories_created': created_stories,
        'todo_by_project': todo_by_project,
        'epics_by_project': epics_by_project,
    }
    if created_epics or created_stories:
        logger.info(
            "[BACKLOG] Rééquilibrage : +%d Epic(s), +%d Story(ies) TO DO",
            created_epics, created_stories
        )
    else:
        logger.info("[BACKLOG] Backlog équilibré — aucune création nécessaire")

    return summary_result


def _find_team_for_project(project_key: str, teams_config: dict) -> str:
    for team in teams_config.get('teams', []):
        if team.get('jira_project_key', '').upper() == project_key.upper():
            return team['id']
    teams = teams_config.get('teams', [])
    return teams[0]['id'] if teams else 'phoenix'


def _find_lead_for_team(team_id: str, members: dict) -> str | None:
    for mid, data in members.items():
        if (data.get('role', '').lower() == 'lead'
                and team_id in data.get('team_ids', [])):
            return mid
    return None