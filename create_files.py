import json
from pathlib import Path

root = Path(__file__).parent
(root / 'config').mkdir(exist_ok=True)
(root / 'providers').mkdir(exist_ok=True)
(root / 'tests').mkdir(exist_ok=True)

files = {
    'config/teams.yaml': '''teams:
  - id: phoenix
    name: "Team Phoenix"
    members:
      - id: alice_m
        display_name: "Alice Martin"
        role: lead
        availability: available
      - id: bob_d
        display_name: "Bob Dupont"
        role: dev
        availability: available
      - id: claire_v
        display_name: "Claire Vidal"
        role: dev
        availability: available
      - id: david_r
        display_name: "David Renard"
        role: qa
        availability: available

  - id: nebula
    name: "Team Nebula"
    members:
      - id: emma_b
        display_name: "Emma Bernard"
        role: lead
        availability: available
      - id: felix_g
        display_name: "Félix Garcia"
        role: dev
        availability: available
      - id: grace_l
        display_name: "Grace Lambert"
        role: dev
        availability: available
''',
    'config/scenarios.yaml': '''scenarios:
  - id: add_comment
    type: add_comment
    weight: 40
    description: "Un membre de l'équipe ajoute un commentaire de suivi sur un ticket"

  - id: change_status
    type: change_status
    weight: 30
    description: "Un ticket avance dans le workflow (To Do → In Progress → In Review → Done)"

  - id: change_assignee
    type: change_assignee
    weight: 10
    description: "Un ticket est réassigné à un autre membre de l'équipe"

  - id: block_ticket
    type: block_ticket
    weight: 8
    description: "Un ticket est bloqué — le membre explique le blocage en commentaire"

  - id: set_absence
    type: set_absence
    weight: 4
    description: "Un membre part en absence, ses tickets ouverts sont réassignés"

  - id: return_from_absence
    type: return_from_absence
    weight: 4
    description: "Un membre revient d'absence et redevient disponible"

  - id: add_subtask
    type: add_subtask
    weight: 4
    description: "Une sous-tâche est créée sur un ticket existant"
''',
    'providers/__init__.py': '',
    'providers/stub_provider.py': '''import random
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
''',
    'state_manager.py': '''import json
from pathlib import Path
from typing import Any, Dict, List
from logging import getLogger

logger = getLogger(__name__)

class StateManager:
    """Gère la lecture/écriture et les opérations sur l'état du simulateur."""

    def __init__(self, state_file: str = 'state.json') -> None:
        self.state_path = Path(state_file)

    def load(self) -> Dict[str, Any]:
        """Charge le state depuis state.json. Retourne {} si absent."""
        if not self.state_path.exists():
            return {}
        with self.state_path.open('r', encoding='utf-8') as f:
            return json.load(f)

    def save(self, state: Dict[str, Any]) -> None:
        """Sauvegarde le state dans state.json avec indentation."""
        with self.state_path.open('w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def get_available_members(self, team_id: str) -> List[Dict[str, Any]]:
        """Retourne la liste des membres disponibles pour l'équipe."""
        state = self.load()
        members = []
        for member_id, data in state.get('members', {}).items():
            if data.get('team_id') == team_id and data.get('availability') == 'available':
                members.append({'id': member_id, **data})
        return members

    def get_open_tickets(self, team_id: str) -> List[Dict[str, Any]]:
        """Retourne les tickets non-Done pour l'équipe."""
        state = self.load()
        open_tickets = []
        for ticket in state.get('tickets', {}).values():
            if ticket.get('team_id') == team_id and ticket.get('status') != 'Done':
                open_tickets.append(ticket)
        return open_tickets

    def update_member_availability(self, member_id: str, status: str) -> None:
        """Met à jour l'état de disponibilité d'un membre."""
        state = self.load()
        if 'members' not in state or member_id not in state['members']:
            logger.warning('Membre %s introuvable dans state', member_id)
            return
        state['members'][member_id]['availability'] = status
        self.save(state)

    def update_ticket_status(self, ticket_key: str, new_status: str) -> None:
        """Met à jour le statut d'un ticket."""
        state = self.load()
        ticket = state.get('tickets', {}).get(ticket_key)
        if not ticket:
            logger.warning('Ticket %s introuvable dans state', ticket_key)
            return
        ticket['status'] = new_status
        self.save(state)

    def update_ticket_assignee(self, ticket_key: str, new_assignee_id: str) -> None:
        """Réassigne le ticket à un autre membre."""
        state = self.load()
        ticket = state.get('tickets', {}).get(ticket_key)
        if not ticket:
            logger.warning('Ticket %s introuvable dans state', ticket_key)
            return
        ticket['assignee_id'] = new_assignee_id
        self.save(state)
''',
    'scenario_engine.py': '''import random
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
''',
    'ai_writer.py': '''import os
from typing import Any, Dict
from logging import getLogger
from providers.stub_provider import StubProvider

logger = getLogger(__name__)

class AIWriter:
    """Wrapper IA qui charge un provider et génère du texte."""

    def __init__(self, provider_name: str | None = None) -> None:
        self.provider_name = provider_name or os.getenv('AI_PROVIDER', 'stub')
        self.provider = StubProvider()
        logger.info('AIWriter: using provider %s', self.provider_name)

    def generate_content(self, event: Dict[str, Any]) -> str:
        """Génère le contenu textuel pour l'événement via le provider."""
        return self.provider.generate(event)
''',
    'jira_client.py': '''import os
from typing import Any, Dict, List
from logging import getLogger

logger = getLogger(__name__)

class JiraClient:
    """Client Jira avec mode dry-run et gestion basique des opérations."""

    def __init__(self) -> None:
        self.base_url = os.getenv('JIRA_BASE_URL', '')
        self.email = os.getenv('JIRA_EMAIL', '')
        self.api_token = os.getenv('JIRA_API_TOKEN', '')
        self.project_key = os.getenv('JIRA_PROJECT_KEY', '')
        self.dry_run = os.getenv('DRY_RUN', 'true').lower() == 'true'
        logger.info('JiraClient: DRY_RUN=%s — no HTTP calls will be made', self.dry_run)

    def _dry_log(self, action: str, ticket_key: str, details: str) -> Dict[str, Any]:
        message = f'[DRY-RUN] {action} on {ticket_key} → {details}'
        print(message)
        return {'status': 'dry-run', 'action': action, 'ticket_key': ticket_key, 'details': details}

    def add_comment(self, ticket_key: str, body: str) -> Dict[str, Any]:
        if self.dry_run:
            return self._dry_log('add_comment', ticket_key, f'"{body}"')
        return {}

    def transition_ticket(self, ticket_key: str, new_status: str) -> Dict[str, Any]:
        if self.dry_run:
            return self._dry_log('change_status', ticket_key, f"transition to '{new_status}'")
        return {}

    def assign_ticket(self, ticket_key: str, account_id: str) -> Dict[str, Any]:
        if self.dry_run:
            return self._dry_log('change_assignee', ticket_key, f'assign to {account_id}')
        return {}

    def create_subtask(self, parent_key: str, summary: str, assignee_id: str) -> Dict[str, Any]:
        if self.dry_run:
            return self._dry_log('add_subtask', parent_key, f'new subtask "{summary}" assigned to {assignee_id}')
        return {}

    def get_tickets_for_project(self) -> List[Dict[str, Any]]:
        if self.dry_run:
            return [
                {'key': 'PROJ-1', 'summary': 'Setup CI pipeline', 'status': 'In Progress', 'assignee_id': 'alice_m', 'team_id': 'phoenix', 'is_blocked': False},
                {'key': 'PROJ-2', 'summary': 'Implement authentication', 'status': 'To Do', 'assignee_id': 'bob_d', 'team_id': 'phoenix', 'is_blocked': False}
            ]
        return []
''',
    'scheduler.py': '''import yaml
import logging

from state_manager import StateManager
from scenario_engine import ScenarioEngine
from ai_writer import AIWriter
from jira_client import JiraClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

status_flow = ['To Do', 'In Progress', 'In Review', 'Done']


def run_simulation(n_events: int = 3) -> None:
    state_manager = StateManager()
    state = state_manager.load() or {
        'last_run': None,
        'members': {},
        'tickets': {}
    }

    with open('config/teams.yaml', 'r', encoding='utf-8') as f:
        teams_config = yaml.safe_load(f)

    scenario_engine = ScenarioEngine()
    ai_writer = AIWriter()
    jira_client = JiraClient()

    executed = 0
    skipped = 0

    logger.info('Run started — %d events requested', n_events)

    for _ in range(n_events):
        scenario = scenario_engine.pick_scenario()
        event = scenario_engine.build_event(scenario, state, teams_config)

        if event is None:
            logger.info("Scenario '%s' skipped — pas de ressource disponible", scenario.get('type'))
            skipped += 1
            continue

        event['ai_content'] = ai_writer.generate_content(event)
        stype = event['type']
        key = event.get('ticket_key')

        try:
            if stype == 'add_comment':
                jira_client.add_comment(key, event['ai_content'])
            elif stype == 'change_status':
                current = event['context']['current_status']
                next_index = status_flow.index(current) + 1 if current in status_flow else 0
                next_status = status_flow[min(next_index, len(status_flow)-1)]
                jira_client.transition_ticket(key, next_status)
                state_manager.update_ticket_status(key, next_status)
            elif stype == 'change_assignee':
                available_members = [x for x, v in state.get('members', {}).items() if v.get('availability') == 'available']
                if available_members:
                    new_assignee = available_members[0]
                    jira_client.assign_ticket(key, new_assignee)
                    state_manager.update_ticket_assignee(key, new_assignee)
            elif stype == 'block_ticket':
                jira_client.add_comment(key, event['ai_content'])
                state['tickets'][key]['is_blocked'] = True
                state_manager.save(state)
            elif stype == 'set_absence':
                state_manager.update_member_availability(event['member_id'], 'absent')
            elif stype == 'return_from_absence':
                state_manager.update_member_availability(event['member_id'], 'available')
            elif stype == 'add_subtask':
                jira_client.create_subtask(key, event['ai_content'], event['member_id'])
            executed += 1
        except Exception as exc:
            logger.error("Erreur durant l'exécution de %s: %s", stype, exc)
            skipped += 1

    state['last_run'] = 'ok'
    state_manager.save(state)
    logger.info('Run complete — %d events executed, %d skipped', executed, skipped)
    logger.info('State saved to state.json')
''',
    'main.py': '''import argparse
from scheduler import run_simulation

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Jira Activity Simulator')
    parser.add_argument('--events', type=int, default=3, help='Nombre d\'événements à simuler')
    parser.add_argument('--dry-run', action='store_true', help='Force le mode dry-run')
    args = parser.parse_args()
    run_simulation(n_events=args.events)
''',
    'tests/__init__.py': '',
    'README.md': '''# Jira Activity Simulator

Simulateur d'activité Jira Cloud pour équipes Scrum (phase 1).
Génère des événements de type changement de statut, commentaires, réassignations, blocages, absences.
Architecture modulaire, stub IA et mode dry-run.

## Prérequis

- Python 3.11+

## Installation

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

## Configuration

Copiez `.env.example` en `.env` et remplissez les valeurs.

## Lancement

```bash
python main.py --events 5
```

## Variables d'environnement

| Variable | Description | Exemple |
|---|---|---|
| AI_PROVIDER | Provider IA (`stub`/`gemini`/`groq`) | stub |
| JIRA_BASE_URL | URL Jira Cloud | https://your-domain.atlassian.net |
| JIRA_EMAIL | Email Jira | your-email@example.com |
| JIRA_API_TOKEN | Jeton API Jira | your-api-token-here |
| JIRA_PROJECT_KEY | Clé projet Jira | PROJ |
| DRY_RUN | Mode dry-run `true`/`false` | true |
| EVENTS_PER_RUN | Nombre d'événements par run | 3 |

## Modes

- `stub`: génération locale, pas d'IA réelle.
- IA réelle: à implémenter via provider externe.
- `dry-run`: aucune requête HTTP Jira, simulation seule.
- `live`: exécuter les vrais appels Jira (TODO).
'''
}

for path, content in files.items():
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')

state = {
    'last_run': None,
    'members': {
        'alice_m': {'availability': 'available', 'current_tickets': [], 'team_id': 'phoenix'},
        'bob_d': {'availability': 'available', 'current_tickets': [], 'team_id': 'phoenix'},
        'claire_v': {'availability': 'available', 'current_tickets': [], 'team_id': 'phoenix'},
        'david_r': {'availability': 'available', 'current_tickets': [], 'team_id': 'phoenix'},
        'emma_b': {'availability': 'available', 'current_tickets': [], 'team_id': 'nebula'},
        'felix_g': {'availability': 'available', 'current_tickets': [], 'team_id': 'nebula'},
        'grace_l': {'availability': 'available', 'current_tickets': [], 'team_id': 'nebula'}
    },
    'tickets': {
        'PROJ-1': {'key': 'PROJ-1', 'summary': 'Setup CI pipeline', 'status': 'To Do', 'assignee_id': 'alice_m', 'team_id': 'phoenix', 'is_blocked': False},
        'PROJ-2': {'key': 'PROJ-2', 'summary': 'Implement authentication', 'status': 'In Progress', 'assignee_id': 'bob_d', 'team_id': 'phoenix', 'is_blocked': False},
        'PROJ-3': {'key': 'PROJ-3', 'summary': 'Develop API endpoints', 'status': 'In Review', 'assignee_id': 'claire_v', 'team_id': 'phoenix', 'is_blocked': False},
        'PROJ-4': {'key': 'PROJ-4', 'summary': 'Design UI mockups', 'status': 'To Do', 'assignee_id': 'emma_b', 'team_id': 'nebula', 'is_blocked': False},
        'PROJ-5': {'key': 'PROJ-5', 'summary': 'Write e2e tests', 'status': 'In Progress', 'assignee_id': 'felix_g', 'team_id': 'nebula', 'is_blocked': False}
    }
}

Path(root / 'state.json').write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
print('Done')
