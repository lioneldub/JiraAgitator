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
        scenario_type = scenario.get('type')

        for team in teams_config.get('teams', []):
            team_id = team.get('id')
            members = [m for m in team.get('members', []) if state.get('members', {}).get(m['id'], {}).get('availability') == 'available']
            if not members:
                continue
            if scenario_type in ('add_comment', 'change_status', 'change_assignee', 'block_ticket', 'add_subtask'):
                tickets = [t for t in state.get('tickets', {}).values() if t.get('team_id') == team_id and t.get('status') != 'Done']
                if not tickets:
                    continue
            else:
                tickets = []

            member = random.choice(members)
            ticket = random.choice(tickets) if tickets else None

            if scenario_type in ('set_absence', 'return_from_absence'):
                return {
                    'type': scenario_type,
                    'team_id': team_id,
                    'member_id': member['id'],
                    'member_name': member['display_name'],
                    'ticket_key': None,
                    'ticket_summary': None,
                    'context': {},
                    'ai_content': None
                }

            if not ticket:
                continue

            return {
                'type': scenario_type,
                'team_id': team_id,
                'member_id': member['id'],
                'member_name': member['display_name'],
                'ticket_key': ticket['key'],
                'ticket_summary': ticket['summary'],
                'context': {
                    'current_status': ticket.get('status'),
                    'is_blocked': ticket.get('is_blocked', False)
                },
                'ai_content': None
            }

        logger.info("Pas d'événement possible pour le scénario %s", scenario_type)
        return None
