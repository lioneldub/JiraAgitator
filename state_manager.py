import json
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
            team_ids = data.get('team_ids', []) if isinstance(data.get('team_ids', []), list) else [data.get('team_id', '')]
            if team_id in team_ids and data.get('availability') == 'available':
                members.append({'id': member_id, **data})
        return members

    def get_open_tickets(self, team_id: str) -> List[Dict[str, Any]]:
        """Retourne les tickets non-Done pour l'équipe."""
        state = self.load()
        open_tickets = []
        for ticket in state.get('tickets', {}).values():
            if ticket.get('team_id') == team_id and ticket.get('status_category') != 'DONE':
                open_tickets.append(ticket)
        return open_tickets

    def get_status_category(self, status: str) -> str:
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

    def get_tickets_by_type(self, issue_type: str, team_id: str | None = None) -> List[Dict[str, Any]]:
        """Retourne les tickets d'un type donné, optionnellement filtrés par équipe."""
        state = self.load()
        result = []
        for ticket in state.get('tickets', {}).values():
            if ticket.get('issue_type', '').lower() == issue_type.lower():
                if team_id is None or ticket.get('team_id') == team_id:
                    result.append(ticket)
        return result

    def get_epics(self, team_id: str | None = None) -> List[Dict[str, Any]]:
        """Retourne les Epics disponibles (non-DONE)."""
        state = self.load()
        epics = []
        for ticket in state.get('tickets', {}).values():
            if ticket.get('issue_type') == 'Epic' and ticket.get('status_category') != 'DONE':
                if team_id is None or ticket.get('team_id') == team_id:
                    epics.append(ticket)
        return epics

    def get_members_by_role(self, role: str, team_id: str | None = None) -> List[Dict[str, Any]]:
        """Retourne les membres disponibles ayant le rôle spécifié."""
        state = self.load()
        result = []
        for member_id, data in state.get('members', {}).items():
            if data.get('role', '').lower() != role.lower() or data.get('availability') != 'available':
                continue
            team_ids = data.get('team_ids', []) if isinstance(data.get('team_ids', []), list) else [data.get('team_id', '')]
            if team_id is None or team_id in team_ids:
                result.append({'id': member_id, **data})
        return result

    def update_ticket_field(self, ticket_key: str, field: str, value) -> None:
        """Met à jour un champ générique d'un ticket."""
        state = self.load()
        ticket = state.get('tickets', {}).get(ticket_key)
        if not ticket:
            logger.warning('Ticket %s introuvable dans state', ticket_key)
            return
        ticket[field] = value
        import datetime
        ticket['last_updated'] = datetime.datetime.utcnow().isoformat()
        self.save(state)

    def add_subtask_to_parent(self, parent_key: str, subtask_key: str) -> None:
        """Enregistre une sous-tâche dans la liste subtask_keys du parent."""
        state = self.load()
        parent = state.get('tickets', {}).get(parent_key)
        if parent and subtask_key not in parent.get('subtask_keys', []):
            parent.setdefault('subtask_keys', []).append(subtask_key)
            self.save(state)

    def add_issue_link(self, ticket_key: str, linked_key: str, link_type: str) -> None:
        """Ajoute un lien entre deux tickets dans le state."""
        state = self.load()
        ticket = state.get('tickets', {}).get(ticket_key)
        if not ticket:
            logger.warning('Ticket %s introuvable dans state', ticket_key)
            return
        link = {'key': linked_key, 'link_type': link_type}
        if link not in ticket.get('linked_issues', []):
            ticket.setdefault('linked_issues', []).append(link)
            self.save(state)

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
