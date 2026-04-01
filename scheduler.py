from dotenv import load_dotenv
load_dotenv()  # doit être appelé avant toute lecture de os.getenv()

import os
import yaml
import logging
import random

from state_manager import StateManager
from scenario_engine import ScenarioEngine
from ai_writer import AIWriter
from jira_client import JiraClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

status_flow = ['To Do', 'In Progress', 'In Review', 'Done']


def run_simulation(n_events: int = 3, force_dry_run: bool = False) -> None:
    """Lance la simulation — bootstrap automatique si AUTO_BOOTSTRAP=true."""

    # Bootstrap automatique si configuré
    auto_bootstrap = os.getenv('AUTO_BOOTSTRAP', 'false').lower() == 'true'
    if auto_bootstrap:
        from bootstrap_state import bootstrap
        project_keys_raw = os.getenv('JIRA_PROJECT_KEYS',
                                     os.getenv('JIRA_PROJECT_KEY', 'POT'))
        project_list = [p.strip() for p in project_keys_raw.split(',')
                        if p.strip()]
        logger.info("AUTO_BOOTSTRAP=true — rafraîchissement du state depuis Jira...")
        bootstrap(project_list, force_dry_run=force_dry_run)
        logger.info("Bootstrap terminé — state.json à jour")

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
            logger.info(
                "[SKIP] scénario '%s' — aucun ticket/membre éligible",
                scenario.get('id', '?')
            )
            skipped += 1
            continue

        event['ai_content'] = ai_writer.generate_content(event)
        stype = event['type']
        key = event.get('ticket_key')

        try:
            if stype == 'add_comment':
                jira_client.add_comment(key, event['ai_content'])
            elif stype == 'change_status':
                current = event['context'].get('current_status')
                target = event['context'].get('target_status')
                if target:
                    next_status = target
                else:
                    next_index = status_flow.index(current) + 1 if current in status_flow else 0
                    next_status = status_flow[min(next_index, len(status_flow) - 1)]

                jira_client.transition_ticket(key, next_status)
                state_manager.update_ticket_status(key, next_status)
                state_manager.update_ticket_field(key, 'status_category', state_manager.get_status_category(next_status))

                # propagation Epic (70% si Story passe IN PROGRESS)
                if next_status == 'IN PROGRESS' and event.get('issue_type') == 'Story':
                    epic_key = event['context'].get('epic_key')
                    if epic_key and random.random() < 0.70:
                        epic_ticket = state.get('tickets', {}).get(epic_key)
                        if epic_ticket and epic_ticket.get('status_category') == 'TO DO':
                            jira_client.transition_ticket(epic_key, 'IN PROGRESS')
                            state_manager.update_ticket_status(epic_key, 'IN PROGRESS')
                            state_manager.update_ticket_field(epic_key, 'status_category', 'IN PROGRESS')
                            logger.info("Epic %s propagée en IN PROGRESS (70%% rule)", epic_key)

                if next_status == 'BLOCKED':
                    comment = event.get('ai_content') or 'Ticket bloqué — en attente de résolution.'
                    jira_client.add_comment(key, comment)
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
                if key in state.get('tickets', {}):
                    state['tickets'][key]['is_blocked'] = True
                state_manager.save(state)
            elif stype == 'set_absence':
                state_manager.update_member_availability(event['member_id'], 'absent')
            elif stype == 'return_from_absence':
                state_manager.update_member_availability(event['member_id'], 'available')
            elif stype == 'add_subtask':
                new_subtask = jira_client.create_subtask(key, event['ai_content'], event['member_id'])
                if new_subtask.get('key'):
                    state_manager.add_subtask_to_parent(key, new_subtask['key'])
            executed += 1
            logger.info(
                "[OK] %s | %s %s | %s → %s | par %s",
                event.get('ticket_key', '?'),
                event.get('issue_type', '?'),
                f"({event.get('ticket_summary', '')[:40]})",
                event['context'].get('current_status', '?'),
                event['context'].get('target_status', '—'),
                event.get('member_name', '?')
            )
        except Exception as exc:
            logger.error("Erreur durant l'exécution de %s: %s", stype, exc)
            skipped += 1

    state['last_run'] = 'ok'
    state_manager.save(state)
    logger.info('Run complete — %d events executed, %d skipped', executed, skipped)
    logger.info('State saved to state.json')
