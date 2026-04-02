import os
import base64
import yaml
from pathlib import Path
from typing import Any, Dict, List
import requests
from logging import getLogger

from state_manager import StateManager

logger = getLogger(__name__)

class JiraClient:
    """Client Jira avec mode dry-run et gestion basique des opérations."""

    def __init__(self, force_dry_run: bool = False) -> None:
        self.base_url = os.getenv('JIRA_BASE_URL', '')
        self.email = os.getenv('JIRA_EMAIL', '')
        self.api_token = os.getenv('JIRA_API_TOKEN', '')
        self.project_key = os.getenv('JIRA_PROJECT_KEY', '')
        self.dry_run = force_dry_run or os.getenv('DRY_RUN', 'true').lower() == 'true'

        # Charger le mapping member_id → jira_account_id depuis teams.yaml
        self._account_id_map: Dict[str, str] = {}
        teams_path = Path('config/teams.yaml')
        if teams_path.exists():
            with teams_path.open('r', encoding='utf-8') as f:
                teams_cfg = yaml.safe_load(f) or {}
            for team in teams_cfg.get('teams', []):
                for member in team.get('members', []):
                    mid = member.get('id', '')
                    aid = member.get('jira_account_id', '')
                    if mid and aid:
                        self._account_id_map[mid] = aid

        # Cache des priorités : name → id
        self._priority_map: Dict[str, str] = {}
        if not self.dry_run:
            self._load_priorities()

        logger.info('JiraClient: DRY_RUN=%s — no HTTP calls will be made', self.dry_run)
        if not self.dry_run:
            logger.warning(
                "JiraClient: MODE LIVE ACTIF — les appels HTTP vers Jira sont réels !"
            )

    def _get_auth_headers(self) -> Dict[str, str]:
        if not self.email or not self.api_token:
            raise EnvironmentError('JIRA_EMAIL et JIRA_API_TOKEN doivent être définis en mode live')
        credentials = base64.b64encode(
            f"{self.email}:{self.api_token}".encode('utf-8')
        ).decode('utf-8')
        return {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _load_priorities(self) -> None:
        """Charge le mapping nom priorité → ID depuis Jira."""
        try:
            url = f"{self.base_url}/rest/api/3/priority"
            headers = self._get_auth_headers()
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                priorities = response.json()
                for p in priorities:
                    name = p.get('name', '')
                    pid = p.get('id', '')
                    if name and pid:
                        self._priority_map[name] = pid
                logger.info("Priorités chargées: %s", list(self._priority_map.keys()))
            else:
                logger.warning("Échec chargement priorités: HTTP %d", response.status_code)
        except Exception as e:
            logger.warning("Erreur chargement priorités: %s", e)

    def _get_status_category(self, status: str) -> str:
        """Retourne la catégorie normalisée d'un statut Jira (insensible à la casse)."""
        s = status.strip().upper()
        todo_statuses     = {'IDEA', 'TO DO', 'TODO', 'OPEN', 'BACKLOG'}
        done_statuses     = {'DONE', 'CLOSED', 'CANCELLED', 'CANCELED',
                             'RESOLVED', 'COMPLETE', 'COMPLETED'}
        if s in todo_statuses:
            return 'TO DO'
        elif s in done_statuses:
            return 'DONE'
        else:
            return 'IN PROGRESS'

    def _handle_response(self, response: requests.Response, action: str) -> Dict[str, Any]:
        if response.status_code in (200, 201, 204):
            if response.content:
                return response.json()
            return {}
        elif response.status_code == 401:
            logger.error('Auth invalide — vérifier JIRA_EMAIL / JIRA_API_TOKEN')
            raise PermissionError('Jira 401 Unauthorized')
        elif response.status_code == 403:
            logger.error('Permission refusée sur %s', action)
            raise PermissionError('Jira 403 Forbidden')
        elif response.status_code == 404:
            logger.warning('Ressource introuvable pour %s', action)
            return {}
        elif response.status_code == 429:
            logger.warning('Rate limit Jira — attente 60s puis retry')
            import time
            time.sleep(60)
            raise RuntimeError('Jira 429 RateLimit — événement non exécuté')
        else:
            logger.error('Jira %s erreur %d: %s', action, response.status_code, response.text[:200])
            raise RuntimeError(f'Jira {response.status_code} on {action}')

    def _dry_log(self, action: str, ticket_key: str, details: str) -> Dict[str, Any]:
        message = f'[DRY-RUN] {action} on {ticket_key} → {details}'
        print(message)
        return {'status': 'dry-run', 'action': action, 'ticket_key': ticket_key, 'details': details}

    def add_comment(self, ticket_key: str, body: str) -> Dict[str, Any]:
        if self.dry_run:
            return self._dry_log('add_comment', ticket_key, f'"{body[:80]}..."' if len(body) > 80 else f'"{body}"')

        url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/comment"
        payload = {
            'body': {
                'type': 'doc',
                'version': 1,
                'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': body}]}]
            }
        }
        headers = self._get_auth_headers()
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        return self._handle_response(response, f'add_comment({ticket_key})')

    def _get_transition_id(self, ticket_key: str, target_status: str) -> str | None:
        url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/transitions"
        headers = self._get_auth_headers()
        response = requests.get(url, headers=headers, timeout=15)
        data = self._handle_response(response, 'get_transitions')

        transitions = data.get('transitions', [])
        for t in transitions:
            if t.get('to', {}).get('name', '').lower() == target_status.lower():
                return t.get('id')
        logger.warning("Transition '%s' non trouvée pour %s", target_status, ticket_key)
        return None

    def transition_ticket(self, ticket_key: str, new_status: str) -> Dict[str, Any]:
        if self.dry_run:
            return self._dry_log('change_status', ticket_key, f"transition to '{new_status}'")

        transition_id = self._get_transition_id(ticket_key, new_status)
        if not transition_id:
            logger.warning("Transition ignorée — ID introuvable pour '%s'", new_status)
            return {}

        url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/transitions"
        payload = {'transition': {'id': transition_id}}
        headers = self._get_auth_headers()
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        return self._handle_response(response, f'transition_ticket({ticket_key}→{new_status})')

    def assign_ticket(self, ticket_key: str, account_id: str) -> Dict[str, Any]:
        """Réassigne le ticket. Ignore silencieusement si accountId inconnu."""
        # Si account_id est déjà un Jira accountId valide, on l'utilise tel quel.
        resolved_id = self._account_id_map.get(account_id, account_id)

        if self.dry_run:
            return self._dry_log('change_assignee', ticket_key,
                                 f'assign to {account_id} (accountId: {resolved_id})')

        if not resolved_id:
            logger.warning(
                "assign_ticket ignoré pour %s — accountId non résolu pour '%s'. "
                "Remplir jira_account_id dans config/teams.yaml.",
                ticket_key, account_id
            )
            return {'status': 'skipped', 'reason': 'unresolved_account_id'}

        # Si resolved_id est toujours le même et que nous n'avons pas de mapping, c'est peut-être déjà un ID Jira.
        if account_id == resolved_id and account_id in self._account_id_map.values():
            pass
        elif account_id == resolved_id and account_id not in self._account_id_map.values():
            # Si on ne le reconnaît pas du tout, on skip pour éviter échec Jira.
            logger.warning(
                "assign_ticket ignoré pour %s — accountId non résolu pour '%s'. "
                "Remplir jira_account_id dans config/teams.yaml.",
                ticket_key, account_id
            )
            return {'status': 'skipped', 'reason': 'unresolved_account_id'}


        url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/assignee"
        r = requests.put(
            url,
            headers=self._get_auth_headers(),
            json={"accountId": resolved_id},
            timeout=15
        )
        return self._handle_response(r, f"assign_ticket({ticket_key})")

    def create_subtask(self, parent_key: str, summary: str, assignee_id: str) -> Dict[str, Any]:
        if self.dry_run:
            return self._dry_log('add_subtask', parent_key, f'new subtask "{summary}" assigned to {assignee_id}')

        project_key = self.project_key
        if parent_key and '-' in parent_key:
            project_key = parent_key.split('-')[0]

        payload = {
            'fields': {
                'project': {'key': project_key},
                'parent': {'key': parent_key},
                'summary': summary,
                'issuetype': {'name': 'Sub-task'},
                'assignee': {'accountId': assignee_id}
            }
        }

        url = f"{self.base_url}/rest/api/3/issue"
        headers = self._get_auth_headers()
        response = requests.post(url, json=payload, headers=headers, timeout=15)

        if response.status_code == 400:
            try:
                data = response.json()
            except Exception:
                data = {}
            errors = data.get('errors', {})
            if 'issuetype' in errors or 'issuetype' in (data.get('errorMessages') or []):
                payload['fields']['issuetype'] = {'name': 'Task'}
                payload['fields'].pop('parent', None)
                response = requests.post(url, json=payload, headers=headers, timeout=15)

        return self._handle_response(response, f'create_subtask({parent_key})')

    def get_tickets_for_project(self,
                                 project_key: str | None = None) -> List[Dict[str, Any]]:
        """Récupère les tickets ouverts. project_key override self.project_key si fourni."""
        key = project_key or self.project_key
        if self.dry_run:
            return [
                {'key': f'{key}-1', 'summary': 'Setup CI pipeline',
                 'issue_type': 'Story', 'status': 'IN PROGRESS',
                 'status_category': 'IN PROGRESS', 'priority': 'High',
                 'assignee_id': '', 'is_blocked': False,
                 'epic_key': None, 'parent_key': None,
                 'subtask_keys': [], 'linked_issues': [],
                 'story_points': 5, 'last_updated': None},
                {'key': f'{key}-2', 'summary': 'Implement authentication',
                 'issue_type': 'Epic', 'status': 'TO DO',
                 'status_category': 'TO DO', 'priority': 'High',
                 'assignee_id': '', 'is_blocked': False,
                 'epic_key': None, 'parent_key': None,
                 'subtask_keys': [], 'linked_issues': [],
                 'story_points': None, 'last_updated': None},
                {'key': f'{key}-3', 'summary': 'Fix login timeout bug',
                 'issue_type': 'Bug', 'status': 'IN REVIEW',
                 'status_category': 'IN PROGRESS', 'priority': 'Medium',
                 'assignee_id': '', 'is_blocked': False,
                 'epic_key': None, 'parent_key': None,
                 'subtask_keys': [], 'linked_issues': [],
                 'story_points': 3, 'last_updated': None},
            ]

        # Nouvel endpoint Atlassian — POST /rest/api/3/search/jql
        url = f"{self.base_url}/rest/api/3/search/jql"
        payload = {
            "jql": (f"project = {key} "
                    f"AND statusCategory != Done "
                    f"ORDER BY updated DESC"),
            "maxResults": 100,
            "fields": [
                "summary", "status", "assignee", "issuetype", "priority",
                "parent", "subtasks", "issuelinks", "customfield_10016",
                "customfield_10014"
            ]
        }
        r = requests.post(
            url,
            headers=self._get_auth_headers(),
            json=payload,
            timeout=15
        )
        data = self._handle_response(r, f"get_tickets_for_project({key})")

        # Construire le reverse-map accountId → member_id depuis teams.yaml
        import yaml
        account_to_member: dict[str, str] = {}
        teams_path = Path('config/teams.yaml')
        if teams_path.exists():
            with teams_path.open('r', encoding='utf-8') as f:
                teams_config = yaml.safe_load(f) or {}
                for team in teams_config.get('teams', []):
                    for m in team.get('members', []):
                        aid = m.get('jira_account_id', '')
                        if aid:
                            account_to_member[aid] = m['id']

        tickets = []
        sm = StateManager()

        def resolve_assignee(raw_assignee_id: str) -> str:
            if not raw_assignee_id:
                return ''
            low = raw_assignee_id.strip().lower()
            if low in account_to_member:
                return account_to_member[low]
            # Si l'ID envoyé est déjà un member_id
            if any(raw_assignee_id == m.get('id') for team in teams_config.get('teams', []) for m in team.get('members', [])):
                return raw_assignee_id
            # match display_name
            for team in teams_config.get('teams', []):
                for m in team.get('members', []):
                    if m.get('display_name', '').strip().lower() == low:
                        return m['id']
                    if m.get('id', '').strip().lower() == low:
                        return m['id']
                    if m.get('jira_account_id', '').strip().lower() == low:
                        return m['id']
            return raw_assignee_id

        for issue in data.get('issues', []):
            fields = issue.get('fields', {})
            assignee = fields.get('assignee') or {}
            raw_status = fields.get('status', {}).get('name', 'TO DO')
            status_name = raw_status.strip().upper()   # normalisation immédiate
            
            # Résoudre l'assignee depuis accountId vers member_id
            raw_assignee_id = assignee.get('accountId', '')
            resolved_assignee = resolve_assignee(raw_assignee_id)

            # Résolution de l'epic parent
            epic_key = None
            parent = fields.get('parent')
            parent_key = None
            if parent:
                parent_type = (parent.get('fields', {})
                               .get('issuetype', {}).get('name', ''))
                if parent_type == 'Epic':
                    epic_key = parent.get('key')
                else:
                    parent_key = parent.get('key')
            # Fallback : champs custom epic link
            if not epic_key:
                epic_key = (fields.get('customfield_10014')
                            or fields.get('customfield_10008'))

            subtask_keys = [s['key'] for s in fields.get('subtasks', [])]

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

            story_points = (fields.get('customfield_10016')
                            or fields.get('customfield_10028'))

            tickets.append({
                'key': issue['key'],
                'summary': fields.get('summary', ''),
                'issue_type': fields.get('issuetype', {}).get('name', 'Story'),
                'status': status_name,
                'status_category': sm.get_status_category(status_name),
                'priority': fields.get('priority', {}).get('name', 'Medium'),
                'assignee_id': resolved_assignee,
                'epic_key': epic_key,
                'parent_key': parent_key,
                'subtask_keys': subtask_keys,
                'linked_issues': linked_issues,
                'story_points': story_points,
                'is_blocked': status_name.upper() == 'BLOCKED',
                'last_updated': None
            })

        logger.info("get_tickets_for_project(%s) : %d ticket(s)", key, len(tickets))
        return tickets

    def update_issue_field(self, ticket_key: str, field_name: str, value) -> Dict[str, Any]:
        """Met à jour un champ d'un ticket (priority, story_points, description…)."""
        if self.dry_run:
            return self._dry_log('update_field', ticket_key, f'{field_name} = {value}')
        url = f"{self.base_url}/rest/api/3/issue/{ticket_key}"
        r = requests.put(
            url,
            headers=self._get_auth_headers(),
            json={"fields": {field_name: value}},
            timeout=15
        )
        return self._handle_response(r, f"update_issue_field({ticket_key}.{field_name})")

    def create_issue_link(self, from_key: str, to_key: str, link_type: str) -> Dict[str, Any]:
        """Crée un lien entre deux tickets."""
        if self.dry_run:
            return self._dry_log('create_link', from_key, f'{link_type} → {to_key}')

        def _post_link_payload(payload):
            r = requests.post(
                url,
                headers=self._get_auth_headers(),
                json=payload,
                timeout=15
            )
            return r

        url = f"{self.base_url}/rest/api/3/issueLink"
        payload = {
            "type": {"name": link_type.title()},
            "inwardIssue": {"key": from_key},
            "outwardIssue": {"key": to_key}
        }

        r = _post_link_payload(payload)
        if r.status_code in (400, 404):
            # fallback vers Blocks/Is blocked by si 1er type non supporté
            if 'blocked' in link_type.lower():
                alt_payload = {
                    "type": {"name": "Blocks"},
                    "inwardIssue": {"key": to_key},
                    "outwardIssue": {"key": from_key}
                }
                r = _post_link_payload(alt_payload)
            elif link_type.lower() in ('relates to', 'blocks'):
                alt_payload = {
                    "type": {"name": "Relates"},
                    "inwardIssue": {"key": from_key},
                    "outwardIssue": {"key": to_key}
                }
                r = _post_link_payload(alt_payload)

        if r.status_code == 404:
            logger.warning("create_issue_link skipped (%s→%s) HTTP 404, lien impossible", from_key, to_key)
            return {}

        return self._handle_response(r, f"create_issue_link({from_key}→{to_key})")

    def create_issue(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Crée un nouveau ticket Jira."""
        # assurer la présence du project key
        project_key = (fields.get('project', {}).get('key')
                       or fields.get('project', {}).get('id')
                       or self.project_key)
        if project_key:
            fields.setdefault('project', {'key': project_key})

        # Convertir le nom de priorité en ID si nécessaire
        if 'priority' in fields:
            priority_value = fields['priority']
            if isinstance(priority_value, str) and priority_value in self._priority_map:
                fields['priority'] = {'id': self._priority_map[priority_value]}
            elif isinstance(priority_value, str):
                # Si c'est une string mais pas dans le mapping, essayer de l'utiliser comme ID
                fields['priority'] = {'id': priority_value}
            # Si c'est déjà un dict avec 'id', le laisser tel quel

        if self.dry_run:
            summary = fields.get('summary', 'Nouveau ticket')
            issue_type = fields.get('issuetype', {}).get('name', 'Story')
            priority_info = fields.get('priority', {})
            if isinstance(priority_info, dict):
                priority_name = f" (priority id: {priority_info.get('id', 'unknown')})"
            else:
                priority_name = f" (priority: {priority_info})"
            return self._dry_log('create_issue', project_key or self.project_key,
                                 f'{issue_type}: "{summary[:60]}"{priority_name}')

        if not project_key:
            raise ValueError('Jira create_issue requis project key non vide')

        url = f"{self.base_url}/rest/api/3/issue"
        response = requests.post(
            url,
            headers=self._get_auth_headers(),
            json={"fields": fields},
            timeout=15
        )

        if response.status_code == 400:
            data = {}
            try:
                data = response.json()
            except Exception:
                pass
            errors = data.get('errors', {})
            # Gestion « customfield non sur écran »
            if any(k.startswith('customfield_') for k in errors):
                for k in list(errors.keys()):
                    if k.startswith('customfield_'):
                        fields.pop(k, None)
                response = requests.post(
                    url,
                    headers=self._get_auth_headers(),
                    json={"fields": fields},
                    timeout=15
                )

        return self._handle_response(response, "create_issue")
