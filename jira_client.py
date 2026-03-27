import os
import base64
import yaml
from pathlib import Path
from typing import Any, Dict, List
import requests
from logging import getLogger

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

        logger.info('JiraClient: DRY_RUN=%s — no HTTP calls will be made', self.dry_run)

    def _get_auth_headers(self) -> Dict[str, str]:
        if not self.email or not self.api_token:
            raise EnvironmentError('JIRA_EMAIL et JIRA_API_TOKEN doivent être définis en mode live')
        credentials = base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()
        return {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

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
        """Réassigne le ticket. Résout member_id → jira_account_id si nécessaire."""
        resolved_id = self._account_id_map.get(account_id, account_id)
        if self.dry_run:
            return self._dry_log('change_assignee', ticket_key,
                                 f'assign to {account_id} (accountId: {resolved_id})')

        url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/assignee"
        payload = {'accountId': resolved_id}
        headers = self._get_auth_headers()
        response = requests.put(url, json=payload, headers=headers, timeout=15)
        return self._handle_response(response, f'assign_ticket({ticket_key}->{resolved_id})')

    def create_subtask(self, parent_key: str, summary: str, assignee_id: str) -> Dict[str, Any]:
        if self.dry_run:
            return self._dry_log('add_subtask', parent_key, f'new subtask "{summary}" assigned to {assignee_id}')

        url = f"{self.base_url}/rest/api/3/issue"
        payload = {
            'fields': {
                'project': {'key': self.project_key},
                'parent': {'key': parent_key},
                'summary': summary,
                'issuetype': {'name': 'Sub-task'},
                'assignee': {'accountId': assignee_id}
            }
        }
        headers = self._get_auth_headers()
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        return self._handle_response(response, f'create_subtask({parent_key})')

    def get_tickets_for_project(self) -> List[Dict[str, Any]]:
        if self.dry_run:
            return [
                {'key': 'PROJ-1', 'summary': 'Setup CI pipeline', 'status': 'In Progress', 'assignee_id': 'alice_m', 'team_id': 'phoenix', 'is_blocked': False},
                {'key': 'PROJ-2', 'summary': 'Implement authentication', 'status': 'To Do', 'assignee_id': 'bob_d', 'team_id': 'phoenix', 'is_blocked': False}
            ]

        url = (f"{self.base_url}/rest/api/3/search"
               f"?jql=project={self.project_key}+AND+statusCategory!=Done"
               f"&maxResults=50&fields=summary,status,assignee")
        headers = self._get_auth_headers()
        response = requests.get(url, headers=headers, timeout=15)
        data = self._handle_response(response, 'get_tickets_for_project')

        tickets = []
        for issue in data.get('issues', []):
            fields = issue.get('fields', {})
            assignee = fields.get('assignee') or {}
            tickets.append({
                'key': issue.get('key'),
                'summary': fields.get('summary', ''),
                'status': fields.get('status', {}).get('name', 'To Do'),
                'assignee_id': assignee.get('accountId', ''),
                'team_id': self.project_key.lower(),
                'is_blocked': False
            })
        return tickets
