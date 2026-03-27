import os
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
