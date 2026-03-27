from dotenv import load_dotenv
load_dotenv()  # doit être appelé avant toute lecture de os.getenv()

import yaml
import logging

from state_manager import StateManager
from scenario_engine import ScenarioEngine
from ai_writer import AIWriter
from jira_client import JiraClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

status_flow = ['To Do', 'In Progress', 'In Review', 'Done']


def run_simulation(n_events: int = 3, force_dry_run: bool = False) -> None:
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
    jira_client = JiraClient(force_dry_run=force_dry_run)

    executed = 0
    skipped = 0

    logger.info('Run started — %d events requested', n_events)

    for _ in range(n_events):
        state = state_manager.load()  # Recharger state à chaque itération pour rester en sync

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
                current_assignee = state.get('tickets', {}).get(key, {}).get('assignee_id')
                candidates = [x for x, v in state.get('members', {}).items()
                              if v.get('availability') == 'available' and x != current_assignee]
                if candidates:
                    import random
                    new_assignee = random.choice(candidates)
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
