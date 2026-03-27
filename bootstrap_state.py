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


def bootstrap(project_key: str, force_dry_run: bool = False) -> None:
    """Reconstruit state.json depuis Jira ou les fixtures dry-run."""
    jira = JiraClient(force_dry_run=force_dry_run)
    state_mgr = StateManager()

    logger.info("Récupération des tickets pour le projet %s...", project_key)
    tickets_raw = jira.get_tickets_for_project()

    with open('config/teams.yaml', 'r', encoding='utf-8') as f:
        teams_config = yaml.safe_load(f)

    members: dict = {}
    for team in teams_config.get('teams', []):
        for m in team.get('members', []):
            members[m['id']] = {
                'availability': m.get('availability', 'available'),
                'current_tickets': [],
                'team_id': team['id'],
                'display_name': m.get('display_name', ''),
                'role': m.get('role', 'dev')
            }

    tickets: dict = {}
    for t in tickets_raw:
        tickets[t['key']] = t

    state = {
        'last_run': None,
        'members': members,
        'tickets': tickets
    }
    state_mgr.save(state)
    logger.info("Bootstrap terminé — %d ticket(s), %d membre(s) chargés",
                len(tickets), len(members))
    logger.info("State sauvegardé dans state.json")

    # Afficher un résumé lisible
    if tickets:
        logger.info("Tickets chargés :")
        for key, ticket in tickets.items():
            logger.info("  %s | %-30s | %s | %s",
                        key,
                        ticket.get('summary', '')[:30],
                        ticket.get('status', ''),
                        ticket.get('assignee_id', 'non assigné'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bootstrap state depuis Jira')
    parser.add_argument('--project',
                        default=os.getenv('JIRA_PROJECT_KEY', 'PROJ'),
                        help='Clé du projet Jira')
    parser.add_argument('--dry-run', action='store_true',
                        help='Utiliser les fixtures (pas d\'appel Jira réel)')
    args = parser.parse_args()
    bootstrap(args.project, force_dry_run=args.dry_run)
