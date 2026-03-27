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
