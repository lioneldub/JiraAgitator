import random
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from logging import getLogger

logger = getLogger(__name__)

class ScenarioEngine:
    """Moteur de scénarios pour choisir et construire des événements."""

    def __init__(self, scenarios_file: str = 'config/scenarios.yaml') -> None:
        self.scenarios_path = Path(scenarios_file)
        self.scenarios = self._load_scenarios()

    def _load_scenarios(self) -> List[Dict[str, Any]]:
        with self.scenarios_path.open('r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data.get('scenarios', [])

    def pick_scenario(self) -> Dict[str, Any]:
        """Tire un scénario au sort selon les poids déclarés."""
        weights = [s.get('weight', 1) for s in self.scenarios]
        choice = random.choices(self.scenarios, weights=weights, k=1)[0]
        logger.info('Scenario choisi : %s', choice.get('type'))
        return choice

    def build_event(self, scenario: Dict[str, Any], state: Dict[str, Any], teams_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Construit un événement prêt à être exécuté."""
        constraints = scenario.get('constraints', {})
        allowed_types = constraints.get('issue_types')
        allowed_statuses = constraints.get('statuses')
        actor_roles = constraints.get('actor_roles')
        target_status = constraints.get('target_status')
        guard = constraints.get('guard')

        # 1. Filtrer les tickets candidats
        candidates = []
        for ticket in state.get('tickets', {}).values():
            if allowed_types and ticket.get('issue_type') not in allowed_types:
                continue
            # Comparaison insensible à la casse pour les statuts
            ticket_status = ticket.get('status', '').strip().upper()
            if allowed_statuses:
                allowed_upper = [s.strip().upper() for s in allowed_statuses]
                if ticket_status not in allowed_upper:
                    continue
            # Pareil pour status_category
            ticket_cat = ticket.get('status_category', '').strip().upper()
            if ticket_cat == 'DONE':
                continue
            if guard == 'no_open_subtasks':
                subtasks = ticket.get('subtask_keys', [])
                open_subs = [t for t in subtasks if state.get('tickets', {}).get(t, {}).get('status_category') == 'IN PROGRESS']
                if open_subs:
                    continue
            candidates.append(ticket)

        if not candidates and scenario.get('type') not in ('set_absence', 'return_from_absence'):
            logger.info("Aucun ticket candidat pour le scénario '%s'", scenario.get('id'))
            return None

        # 2. Choisir un ticket si nécessaire
        ticket = random.choice(candidates) if candidates else None
        team_id = ticket.get('team_id') if ticket else None

        # 3. Filtrer les membres selon rôle et équipe
        available_members = []
        for member_id, member in state.get('members', {}).items():
            if member.get('availability') != 'available':
                continue
            team_ids = member.get('team_ids') if member.get('team_ids') else [member.get('team_id', '')]
            if not isinstance(team_ids, list):
                team_ids = [team_ids]
            if team_id and team_id not in team_ids:
                continue

            # role from state or fallback to team config
            role = member.get('role')
            if not role:
                for team in teams_config.get('teams', []):
                    for m in team.get('members', []):
                        if m.get('id') == member_id:
                            role = m.get('role')
                            break
                    if role:
                        break
            role = role or 'dev'

            if actor_roles and role.lower() not in [r.lower() for r in actor_roles]:
                continue

            available_members.append({'id': member_id, **member, 'role': role})

        if not available_members:
            logger.info("Aucun membre disponible pour le scénario '%s'", scenario.get('id'))
            return None

        member = random.choice(available_members)

        if scenario.get('type') in ('set_absence', 'return_from_absence'):
            return {
                'type': scenario.get('type'),
                'team_id': team_id,
                'member_id': member['id'],
                'member_name': member.get('display_name'),
                'member_role': member.get('role', 'dev'),
                'ticket_key': None,
                'ticket_summary': None,
                'context': {},
                'ai_content': None
            }

        if not ticket:
            logger.info("Aucun ticket trouvé pour le scénario '%s'", scenario.get('id'))
            return None

        logger.info(
            "Scénario '%s' → ticket %s [%s] statut '%s' assigné à %s (%s)",
            scenario.get('id'),
            ticket['key'],
            ticket.get('issue_type', '?'),
            ticket.get('status', '?'),
            member.get('display_name', member['id']),
            member.get('role', '?')
        )
        return {
            'type': scenario.get('type'),
            'scenario_id': scenario.get('id'),
            'team_id': team_id,
            'member_id': member['id'],
            'member_name': member.get('display_name', member['id']),
            'member_role': member.get('role', 'dev'),
            'ticket_key': ticket['key'],
            'ticket_summary': ticket.get('summary', ''),
            'issue_type': ticket.get('issue_type', 'Story'),
            'context': {
                'current_status': ticket.get('status'),
                'status_category': ticket.get('status_category'),
                'target_status': target_status,
                'is_blocked': ticket.get('is_blocked', False),
                'priority': ticket.get('priority', 'Medium'),
                'epic_key': ticket.get('epic_key'),
                'requires_ai_comment': constraints.get('requires_ai_comment', False)
            },
            'ai_content': None
        }
