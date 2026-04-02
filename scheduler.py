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
                is_bulk  = event['context'].get('is_bulk', False)
                bulk_max = event['context'].get('bulk_max', 4)
                target   = event['context'].get('target_status', '')

                if is_bulk:
                    # Chercher jusqu'à bulk_max tickets supplémentaires du même statut/type
                    project_prefix = key.split('-')[0]
                    constraints_types = event['context'].get('allowed_types', [])
                    bulk_candidates = [
                        t['key'] for t in state.get('tickets', {}).values()
                        if t['key'] != key
                        and t.get('status', '').upper() == event['context'].get('current_status', '')
                        and (not constraints_types or t.get('issue_type') in constraints_types)
                    ][:bulk_max - 1]   # -1 car le ticket principal est déjà traité

                    all_keys = [key] + bulk_candidates
                    for bulk_key in all_keys:
                        jira_client.transition_ticket(bulk_key, target)
                        state_manager.sync_ticket_after_event(bulk_key, {'status': target})
                    logger.info(
                        "[BULK] %d tickets passés en %s : %s",
                        len(all_keys), target, ', '.join(all_keys)
                    )
                    executed += 1
                    continue   # Passer à l'événement suivant sans le traitement standard

                # Exécuter la transition standard
                jira_client.transition_ticket(key, target)
                state_manager.sync_ticket_after_event(key, {'status': target})

                comment_prob = float(os.getenv('COMMENT_ON_TRANSITION', '0.30'))
                add_comment  = False
                is_blocking  = target.upper() == 'BLOCKED'

                if is_blocking:
                    # BLOCKED : commentaire obligatoire
                    add_comment = True
                elif random.random() < comment_prob:
                    # Autres transitions : commentaire probabiliste
                    add_comment = True

                if add_comment:
                    # Enrichir l'event avec le contexte de transition pour le prompt IA
                    event['context']['transition_comment'] = True
                    event['context']['status_destination'] = target
                    comment_text = ai_writer.generate_content(event)
                    jira_client.add_comment(key, comment_text)
                    logger.info(
                        "[COMMENT] Commentaire ajouté sur %s (%s → %s)",
                        key, event['context'].get('current_status', '?'), target
                    )

                # BLOCKED : parfois ajouter un lien "blocked by" (30% de chance)
                if is_blocking and random.random() < 0.30:
                    # Chercher un ticket candidat bloquant dans le même projet
                    project_prefix = key.split('-')[0]
                    candidates_blocking = [
                        t['key'] for t in state.get('tickets', {}).values()
                        if t['key'] != key
                        and t['key'].startswith(project_prefix)
                        and t.get('status_category') != 'DONE'
                        and t.get('issue_type') in ('Bug', 'Story', 'Task')
                    ]
                    if candidates_blocking:
                        blocking_key = random.choice(candidates_blocking)
                        jira_client.create_issue_link(key, blocking_key, 'is blocked by')
                        state_manager.add_issue_link(key, blocking_key, 'is blocked by')
                        logger.info(
                            "[LINK] %s is blocked by %s (ajout automatique)",
                            key, blocking_key
                        )

                # propagation Epic (70% si Story passe IN PROGRESS)
                if target == 'IN PROGRESS' and event.get('issue_type') == 'Story':
                    epic_key = event['context'].get('epic_key')
                    if epic_key and random.random() < 0.70:
                        epic_ticket = state.get('tickets', {}).get(epic_key)
                        if epic_ticket and epic_ticket.get('status_category') == 'TO DO':
                            jira_client.transition_ticket(epic_key, 'IN PROGRESS')
                            state_manager.sync_ticket_after_event(epic_key, {'status': 'IN PROGRESS'})
                            logger.info("Epic %s propagée en IN PROGRESS (70%% rule)", epic_key)

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
                    'priority': priority,  # Changé de {'name': priority} à priority
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
                link_type    = event['context'].get('link_type', 'relates to')
                cross_project = event['context'].get('cross_project', False)
                from_key  = event['ticket_key']
                from_project = from_key.split('-')[0] if '-' in from_key else ''

                candidates = [
                    t['key'] for t in state.get('tickets', {}).values()
                    if t['key'] != from_key
                    and t.get('status_category') != 'DONE'
                    and (
                        # Cross-project : cibler un autre projet
                        (cross_project and t['key'].split('-')[0] != from_project)
                        or
                        # Même projet si pas cross
                        (not cross_project and t['key'].split('-')[0] == from_project)
                    )
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
            elif stype == 'split_issue':
                source_key   = event['ticket_key']
                source_summ  = event.get('ticket_summary', 'Story complexe')
                epic_key     = event['context'].get('epic_key')
                project_key  = source_key.split('-')[0]
                account_id   = _resolve_account_id(event['member_id'], state_manager)

                # Générer les résumés des deux nouvelles Stories via IA
                part1_content = ai_writer.generate_content({
                    **event,
                    'scenario_id': 'fragmentation_story',
                    'context': {**event['context'],
                                'split_part': 1, 'source_summary': source_summ}
                })
                part2_content = ai_writer.generate_content({
                    **event,
                    'scenario_id': 'fragmentation_story',
                    'context': {**event['context'],
                                'split_part': 2, 'source_summary': source_summ}
                })

                # Créer les deux nouvelles Stories
                for part_summary in [part1_content[:100], part2_content[:100]]:
                    fields = {
                        'project': {'key': project_key},
                        'summary': part_summary,
                        'issuetype': {'name': 'Story'},
                        'priority': event['context'].get('priority', 'Medium'),
                        'assignee': {'accountId': account_id},
                    }
                    if epic_key:
                        fields['parent'] = {'key': epic_key}
                    jira_client.create_issue(fields)

                # Passer la Story source en CANCELLED avec commentaire
                cancel_comment = (f"Story fragmentée en deux tickets plus petits. "
                                  f"Voir les nouvelles Stories créées dans ce sprint.")
                jira_client.add_comment(source_key, cancel_comment)
                jira_client.transition_ticket(source_key, 'CANCELLED')
                state_manager.sync_ticket_after_event(source_key, {'status': 'CANCELLED'})
                logger.info("[SPLIT] %s fragmenté → 2 nouvelles Stories | source CANCELLED",
                            source_key)
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

                elif field_name == 'labels':
                    # Ajouter des labels de version ou domaine
                    label_type = event['context'].get('label_type', 'version')  # 'version' ou 'domain'
                    if label_type == 'version':
                        versions = ['v1.0', 'v1.1', 'v2.0', 'v2.1', 'v3.0']
                        new_label = random.choice(versions)
                    else:  # domain
                        domains = ['frontend', 'backend', 'api', 'database', 'security', 'performance']
                        new_label = random.choice(domains)

                    # Récupérer les labels existants et ajouter le nouveau
                    current_labels = state.get('tickets', {}).get(key, {}).get('labels', [])
                    if new_label not in current_labels:
                        updated_labels = current_labels + [new_label]
                        jira_client.update_issue_field(key, 'labels', updated_labels)
                        state_manager.sync_ticket_after_event(key, {'labels': updated_labels})
                        logger.info("[LABEL] %s ajouté label %s", key, new_label)
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
