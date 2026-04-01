"""
Peuple state.json depuis les vrais tickets Jira (ou fixtures en dry-run).
Usage : python bootstrap_state.py --project PROJ
"""
import os
import argparse
import yaml
from dotenv import load_dotenv
from pathlib import Path
import logging

load_dotenv()

from jira_client import JiraClient
from state_manager import StateManager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')


def _normalize_ticket(issue: dict, default_team_id: str,
                      status_manager) -> dict:
    """Normalise un issue Jira en dict state enrichi."""
    fields = issue.get('fields', {})
    assignee = fields.get('assignee') or {}
    issue_type = fields.get('issuetype', {}).get('name', 'Story')
    raw_status = fields.get('status', {}).get('name', 'TO DO')
    status_name = raw_status.strip().upper()   # ← normaliser ici
    priority = fields.get('priority', {}).get('name', 'Medium')

    # Résolution de l'epic parent
    epic_key = None
    parent = fields.get('parent')
    parent_key = None
    if parent:
        parent_type = parent.get('fields', {}).get('issuetype', {}).get('name', '')

    # Sous-tâches
    subtask_keys = [s['key'] for s in fields.get('subtasks', [])]

    # Liens
    linked_issues = []
    for link in fields.get('issuelinks', []):
        if 'outwardIssue' in link:
            linked_issues.append({
                'key': link['outwardIssue']['key'],
                'link_type': link.get('type', {}).get('outward', 'relates to')
            })
        if 'inwardIssue' in link:
            linked_issues.append({
                'key': link['inwardIssue']['key'],
                'link_type': link.get('type', {}).get('inward', 'is blocked by')
            })

    # Story points (essayer plusieurs champs custom)
    story_points = (fields.get('story_points')
                    or fields.get('customfield_10016')
                    or fields.get('customfield_10028'))

def bootstrap(project_keys: list[str], force_dry_run: bool = False) -> None:
    """
    Reconstruit state.json depuis Jira pour une liste de projets.
    Les membres sont toujours pris depuis config/teams.yaml.
    """
    jira = JiraClient(force_dry_run=force_dry_run)
    state_mgr = StateManager()

    with open('config/teams.yaml', 'r', encoding='utf-8') as f:
        teams_config = yaml.safe_load(f)

    # Construire les membres depuis teams.yaml (source de vérité unique)
    # Déduplication : un même member_id dans plusieurs équipes → team_ids liste
    members: dict = {}
    for team in teams_config.get('teams', []):
        for m in team.get('members', []):
            mid = m['id']
            if mid in members:
                if team['id'] not in members[mid]['team_ids']:
                    members[mid]['team_ids'].append(team['id'])
            else:
                members[mid] = {
                    'availability': m.get('availability', 'available'),
                    'current_tickets': [],
                    'team_ids': [team['id']],
                    'display_name': m.get('display_name', ''),
                    'role': m.get('role', 'dev'),
                    'jira_account_id': m.get('jira_account_id', '')
                }

    # Agréger les tickets de tous les projets
    all_tickets: dict = {}
    for project_key in project_keys:
        logger.info("Bootstrap — récupération des tickets pour %s...", project_key)
        # Trouver l'équipe associée à ce projet (première équipe dont jira_project_key match)
        team_id = _find_team_for_project(project_key, teams_config)
        tickets_raw = jira.get_tickets_for_project(project_key=project_key)
        for t in tickets_raw:
            t['team_id'] = team_id
            all_tickets[t['key']] = t
        logger.info("  → %d ticket(s) récupéré(s) pour %s (équipe: %s)",
                    len(tickets_raw), project_key, team_id)

    state = {
        'last_run': None,
        'members': members,
        'tickets': all_tickets
    }
    state_mgr.save(state)
    logger.info("Bootstrap terminé — %d ticket(s) total, %d membre(s)",
                len(all_tickets), len(members))

    # Afficher un résumé par type de ticket
    from collections import Counter
    type_counts = Counter(t.get('issue_type', '?') for t in all_tickets.values())
    for itype, count in sorted(type_counts.items()):
        logger.info("  %s : %d ticket(s)", itype, count)


def _find_team_for_project(project_key: str, teams_config: dict) -> str:
    """Trouve l'équipe associée à un project_key via jira_project_key dans teams.yaml.
    Fallback sur la première équipe si non trouvé."""
    for team in teams_config.get('teams', []):
        if team.get('jira_project_key', '').upper() == project_key.upper():
            return team['id']
    # Fallback : première équipe
    teams = teams_config.get('teams', [])
    return teams[0]['id'] if teams else 'phoenix'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bootstrap state depuis Jira')
    parser.add_argument(
        '--projects',
        default=os.getenv('JIRA_PROJECT_KEYS',
                         os.getenv('JIRA_PROJECT_KEY', 'POT')),
        help='Clés de projets séparées par des virgules (ex: POT,KAN)'
    )
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    project_list = [p.strip() for p in args.projects.split(',') if p.strip()]
    bootstrap(project_list, force_dry_run=args.dry_run)
