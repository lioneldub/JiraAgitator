from dotenv import load_dotenv
load_dotenv()  # doit être appelé avant toute lecture de os.getenv()

import os
import yaml
import logging
import random
import datetime
from pathlib import Path

from state_manager import StateManager
from scenario_engine import ScenarioEngine
from ai_writer import AIWriter
from jira_client import JiraClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# Logger vers fichier (mode append) pour conserver historique des exécutions
log_file = os.getenv('JIRA_LOG_FILE', 'log.log')
root_logger = logging.getLogger()
if not any(isinstance(h, logging.FileHandler) and Path(getattr(h, 'baseFilename', '')).resolve() == Path(log_file).resolve() for h in root_logger.handlers):
    fh = logging.FileHandler(log_file, encoding='utf-8', mode='a')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S'))
    root_logger.addHandler(fh)

status_flow = ['To Do', 'In Progress', 'In Review', 'Done']


def _resolve_account_id(member_id: str, state_manager: StateManager) -> str:
    """Résout le jira_account_id depuis un member_id via le state."""
    state = state_manager.load()
    member = state.get('members', {}).get(member_id, {})
    return member.get('jira_account_id', member_id)


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

    # Recharger le state après bootstrap
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

    # Rééquilibrage automatique du backlog si configuré
    auto_replenish = os.getenv('AUTO_REPLENISH', 'false').lower() == 'true'
    if auto_replenish:
        from backlog_manager import check_and_replenish
        with open('config/teams.yaml', 'r', encoding='utf-8') as f:
            teams_cfg = yaml.safe_load(f)
        project_keys_raw = os.getenv('JIRA_PROJECT_KEYS',
                                     os.getenv('JIRA_PROJECT_KEY', 'POT'))
        project_list = [p.strip() for p in project_keys_raw.split(',')
                        if p.strip()]
        check_and_replenish(
            project_list, jira_client, state_manager,
            ai_writer, teams_cfg, dry_run=force_dry_run
        )
        # Recharger le state après la création des nouveaux tickets
        state = state_manager.load()

    executed = 0
    skipped = 0

    start_ts = datetime.datetime.now(datetime.timezone.utc)
    last_heartbeat = start_ts
    logger.info('Run started — %d events requested', n_events)
    logger.info('RUN_START %s', start_ts.isoformat())

    for _ in range(n_events):
        state = state_manager.load()  # Recharger state à chaque itération pour rester en sync

        current_ts = datetime.datetime.now(datetime.timezone.utc)
        if (current_ts - last_heartbeat).total_seconds() >= 5:
            logger.info('RUN_HEARTBEAT %s - executed=%d skipped=%d',
                        current_ts.isoformat(), executed, skipped)
            last_heartbeat = current_ts

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
                # Mise-à-jour atomique du state
                state_manager.sync_ticket_after_event(key, {'status': next_status})

                # propagation Epic (70% si Story passe IN PROGRESS)
                if next_status == 'IN PROGRESS' and event.get('issue_type') == 'Story':
                    epic_key = event['context'].get('epic_key')
                    if epic_key and random.random() < 0.70:
                        epic_ticket = state.get('tickets', {}).get(epic_key)
                        if epic_ticket and epic_ticket.get('status_category') == 'TO DO':
                            jira_client.transition_ticket(epic_key, 'IN PROGRESS')
                            state_manager.sync_ticket_after_event(epic_key, {'status': 'IN PROGRESS'})
                            logger.info("Epic %s propagée en IN PROGRESS (70%% rule)", epic_key)

                if next_status == 'BLOCKED':
                    comment = event.get('ai_content') or 'Ticket bloqué — en attente de résolution.'
                    jira_client.add_comment(key, comment)
            elif stype == 'change_assignee':
                assign_to_self = event['context'].get('assign_to_self', False)
                if assign_to_self:
                    new_assignee = event['member_id']
                else:
                    current = event['context'].get('current_assignee_id', '')
                    candidates = [
                        mid for mid, data in state.get('members', {}).items()
                        if data.get('availability') == 'available'
                        and mid != current
                        and event.get('team_id') in data.get('team_ids', [])
                    ]
                    if not candidates:
                        logger.info("[SKIP] change_assignee — aucun candidat disponible")
                        skipped += 1
                        continue
                    new_assignee = random.choice(candidates)

                account_id = _resolve_account_id(new_assignee, state_manager)
                jira_client.assign_ticket(key, account_id)
                state_manager.sync_ticket_after_event(key, {'assignee_id': new_assignee})
            elif stype == 'create_issue':
                constraints = event.get('context', {})
                issue_type  = constraints.get('issue_type_to_create', 'Bug')
                priority    = constraints.get('priority_to_create', 'Medium')
                initial_st  = constraints.get('initial_status', 'TO DO')
                requires_epic = constraints.get('requires_epic', False)

                # Trouver une Epic cible si nécessaire
                epic_key = None
                if requires_epic:
                    epics = [t for t in state.get('tickets', {}).values()
                             if t.get('issue_type') == 'Epic'
                             and t.get('status_category') != 'DONE'
                             and t.get('team_id') == event.get('team_id')]
                    if epics:
                        epic_key = random.choice(epics)['key']

                # Générer un summary propre via le provider IA
                raw_content = event.get('ai_content') or ''
                # Prendre la première phrase comme summary (jusqu'au premier point ou 100 chars)
                summary = raw_content.split('.')[0].strip()[:100] or f"[{issue_type}] Nouveau ticket"

                project = event.get('ticket_key', '').split('-')[0] if event.get('ticket_key') else jira_client.project_key
                fields = {
                    'project': {'key': project},
                    'summary': summary,
                    'issuetype': {'name': issue_type},
                    'priority': {'name': priority},
                }
                if epic_key:
                    # personnalisable via variable d'environnement pour éviter les erreurs "field unknown"
                    epic_link_field = os.getenv('JIRA_EPIC_LINK_FIELD', 'customfield_10014')
                    if epic_link_field:
                        fields[epic_link_field] = epic_key

                account_id = _resolve_account_id(event['member_id'], state_manager)
                if account_id:
                    fields['assignee'] = {'accountId': account_id}

                result = jira_client.create_issue(fields)

                # Si l'issue est créée et doit démarrer en IN PROGRESS
                if initial_st == 'IN PROGRESS' and result.get('key'):
                    new_key = result['key']
                    jira_client.transition_ticket(new_key, 'IN PROGRESS')
            elif stype == 'create_subtask':
                parent_key = event['ticket_key']
                summary    = event.get('ai_content') or "Sous-tâche technique"
                account_id = _resolve_account_id(event['member_id'], state_manager)

                result = jira_client.create_subtask(parent_key, summary, account_id)

                # Mettre à jour subtask_keys du parent dans le state
                if result.get('key'):
                    state_manager.add_subtask_to_parent(parent_key, result['key'])
            elif stype == 'create_link':
                from_key  = event['ticket_key']
                link_type = event['context'].get('link_type', 'relates to')
                from_project = from_key.split('-')[0] if '-' in from_key else ''

                # Choisir un ticket cible différent du ticket source dans le même projet
                candidates = [
                    t['key'] for t in state.get('tickets', {}).values()
                    if t['key'] != from_key
                    and t.get('status_category') != 'DONE'
                    and t.get('team_id') == event.get('team_id')
                    and (t['key'].split('-')[0] if '-' in t['key'] else '') == from_project
                ]
                if candidates:
                    to_key = random.choice(candidates)
                    # Créer d'abord le lien dans Jira, puis mettre à jour l'état local seulement si succès
                    result = jira_client.create_issue_link(from_key, to_key, link_type)
                    if result:
                        state_manager.add_issue_link(from_key, to_key, link_type)
                        # Si lien "is blocked by", mettre à jour is_blocked du ticket source
                        if 'blocked' in link_type.lower():
                            state_manager.sync_ticket_after_event(from_key, {
                                'status': 'BLOCKED',
                                'is_blocked': True
                            })
                            jira_client.transition_ticket(from_key, 'BLOCKED')
                    else:
                        logger.info("[SKIP] create_link %s → %s %s (échec Jira)", from_key, to_key, link_type)
            elif stype == 'update_field':
                field_name = event['context'].get('field_to_update', 'priority')

                if field_name == 'priority':
                    priorities = ['Lowest', 'Low', 'Medium', 'High', 'Highest']
                    current_p  = event['context'].get('priority', 'Medium')
                    current_i  = priorities.index(current_p) if current_p in priorities else 2
                    options = [p for p in priorities if p != current_p]
                    new_priority = random.choice(options)
                    jira_client.update_issue_field(
                        key, 'priority', {'name': new_priority}
                    )
                    state_manager.sync_ticket_after_event(key, {'priority': new_priority})

                elif field_name == 'story_points':
                    sp_options = [1, 2, 3, 5, 8, 13]
                    new_sp = random.choice(sp_options)
                    # story_points = customfield_10016 sur la plupart des instances Jira
                    jira_client.update_issue_field(key, 'customfield_10016', new_sp)
                    state_manager.sync_ticket_after_event(key, {'story_points': new_sp})
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

    end_ts = datetime.datetime.now(datetime.timezone.utc)
    duration = (end_ts - start_ts).total_seconds()

    state['last_run'] = 'ok'
    state_manager.save(state)
    logger.info('Run complete — %d events executed, %d skipped', executed, skipped)
    logger.info('RUN_END %s | duration=%.1fs | executed=%d | skipped=%d',
                end_ts.isoformat(), duration, executed, skipped)
    logger.info('State saved to state.json')
