import random
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from logging import getLogger

logger = getLogger(__name__)

class ScenarioEngine:
    """Moteur de scénarios pour choisir et construire des événements."""

    def __init__(self, scenarios_file: str = 'config/scenarios.yaml') -> None:
        # Use absolute path from module directory if relative path is provided
        if scenarios_file == 'config/scenarios.yaml':
            project_root = Path(__file__).parent
            self.scenarios_path = project_root / scenarios_file
        else:
            self.scenarios_path = Path(scenarios_file)
        self.scenarios = self._load_scenarios()

    def _load_scenarios(self) -> List[Dict[str, Any]]:
        with self.scenarios_path.open('r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data.get('scenarios', [])

    def _pick_ticket_weighted(self, candidates: list[dict]) -> dict:
        """
        Choisit un ticket en favorisant ceux non touchés récemment.
        Un ticket sans last_updated ou mis à jour il y a longtemps a plus de poids.
        """
        import datetime
        import random

        now = datetime.datetime.utcnow()
        weights = []
        for ticket in candidates:
            last = ticket.get('last_updated')
            if not last:
                # Jamais touché = poids maximum
                weights.append(100)
            else:
                try:
                    dt = datetime.datetime.fromisoformat(last)
                    age_hours = max(1, (now - dt).total_seconds() / 3600)
                    # Poids proportionnel à l'ancienneté, plafonné à 100
                    weights.append(min(100, int(age_hours)))
                except ValueError:
                    weights.append(50)

        return random.choices(candidates, weights=weights, k=1)[0]

    def _pick_project_balanced(self, candidates: list[dict],
                                state: dict) -> list[dict]:
        """
        Filtre les candidats pour favoriser le projet le moins récemment actif.
        Retourne une sous-liste des candidats du projet prioritaire.
        """
        import collections
        # Compter les last_updated récents par projet
        project_activity: dict[str, float] = collections.defaultdict(float)
        import datetime
        now = datetime.datetime.utcnow()
        for ticket in state.get('tickets', {}).values():
            last = ticket.get('last_updated')
            if last:
                try:
                    dt = datetime.datetime.fromisoformat(last)
                    age = (now - dt).total_seconds()
                    proj = ticket['key'].split('-')[0]
                    # Accumuler l'activité récente (plus c'est récent, plus c'est élevé)
                    project_activity[proj] += max(0, 86400 - age)
                except ValueError:
                    pass

        # Identifier les projets représentés dans les candidats
        candidate_projects = list({t['key'].split('-')[0] for t in candidates})
        if len(candidate_projects) <= 1:
            return candidates

        # Choisir le projet le moins actif récemment
        least_active = min(candidate_projects,
                           key=lambda p: project_activity.get(p, 0))

        filtered = [t for t in candidates
                    if t['key'].split('-')[0] == least_active]
        # Si aucun candidat dans ce projet après filtrage, retourner tous les candidats
        return filtered if filtered else candidates

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
                # Vérification liens bloquants (bloquant absent = considéré résolu)
                if not self._is_blocking_resolved(ticket, state):
                    continue
            if guard == 'stagnant_ticket':
                import datetime
                last_upd = ticket.get('last_updated')
                if not last_upd:
                    # Jamais mis à jour = considéré stagnant
                    pass
                else:
                    try:
                        dt = datetime.datetime.fromisoformat(last_upd)
                        age = (datetime.datetime.utcnow() - dt).days
                        if age < 3:
                            continue   # Pas assez stagnant
                    except ValueError:
                        pass
            if guard == 'random_80_percent':
                if random.random() > 0.80:
                    continue   # 20% de chance de skipper ce candidat
            if guard == 'epic_majority_done':
                epic_key = ticket['key']
                # Trouver les Stories/Bugs rattachés à cette Epic
                children = [
                    t for t in state.get('tickets', {}).values()
                    if t.get('epic_key') == epic_key
                    and t.get('issue_type') in ('Story', 'Bug', 'Feature', 'Task')
                ]
                if not children:
                    continue   # Epic sans enfants — ne pas clôturer
                done_count = sum(1 for c in children
                                 if c.get('status_category') == 'DONE')
                ratio = done_count / len(children)
                if ratio < 0.70:
                    continue   # Moins de 70% des enfants DONE
                logger.debug(
                    "Epic %s : %d/%d enfants DONE (%.0f%%) — éligible à la clôture",
                    epic_key, done_count, len(children), ratio * 100
                )
            candidates.append(ticket)

        if not candidates and scenario.get('type') not in ('set_absence', 'return_from_absence'):
            logger.info("Aucun ticket candidat pour le scénario '%s'", scenario.get('id'))
            return None

        # 2. Choisir un ticket si nécessaire
        if candidates:
            balanced_candidates = self._pick_project_balanced(candidates, state)
            ticket = self._pick_ticket_weighted(balanced_candidates)
        else:
            ticket = None
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

        # Gestion des scénarios avec target_actor_roles (ex: demande_clarification_metier)
        target_roles = constraints.get('target_actor_roles', [])
        target_member = None
        if target_roles:
            target_candidates = [
                {'id': mid, **data}
                for mid, data in state.get('members', {}).items()
                if data.get('role', '').lower() in [r.lower() for r in target_roles]
                and data.get('availability') == 'available'
                and mid != member['id']
                and team_id in data.get('team_ids', [])
            ]
            if target_candidates:
                target_member = random.choice(target_candidates)

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

        # Enrichir le contexte avec l'Epic summary
        epic_key = ticket.get('epic_key')
        epic_summary = ''
        if epic_key:
            epic_ticket = state.get('tickets', {}).get(epic_key, {})
            epic_summary = epic_ticket.get('summary', '')

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
                'epic_key': epic_key,
                'epic_summary': epic_summary,
                'current_assignee_id': ticket.get('assignee_id', ''),
                'target_member_id': target_member['id'] if target_member else None,
                'target_member_name': target_member.get('display_name', '') if target_member else '',
                'requires_ai_comment': constraints.get('requires_ai_comment', False),
                # Contraintes de création propagées pour les scénarios create_issue
                'issue_type_to_create': constraints.get('issue_type_to_create'),
                'priority_to_create': constraints.get('priority_to_create'),
                'initial_status': constraints.get('initial_status'),
                'requires_epic': constraints.get('requires_epic', False),
                'link_to_parent': constraints.get('link_to_parent', False),
                'link_type': constraints.get('link_type'),
                'field_to_update': constraints.get('field_to_update'),
                'assign_to_self': constraints.get('assign_to_self', False),
            },
            'ai_content': None
        }

    def _is_blocking_resolved(self, ticket: dict, state: dict) -> bool:
        """
        Retourne True si tous les tickets bloquants sont résolus.
        Un ticket bloquant absent du state est considéré comme résolu
        (probablement DONE dans Jira).
        """
        for link in ticket.get('linked_issues', []):
            if link.get('link_type', '').lower() in ('is blocked by',
                                                       'est bloqué par'):
                blocking_key = link['key']
                blocking_ticket = state.get('tickets', {}).get(blocking_key)
                if blocking_ticket is None:
                    # Absent du state = considéré résolu
                    logger.debug(
                        "Ticket bloquant %s absent du state — "
                        "considéré résolu", blocking_key
                    )
                    continue
                if blocking_ticket.get('status_category') != 'DONE':
                    return False
        return True
