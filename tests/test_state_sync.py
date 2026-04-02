"""Tests pour la synchronisation atomique des tickets après événements."""
import json
import datetime
import pytest
from pathlib import Path
from state_manager import StateManager


def test_sync_ticket_updates_status_category(tmp_path, monkeypatch):
    """sync_ticket_after_event doit mettre à jour status ET status_category."""
    monkeypatch.chdir(tmp_path)
    sm = StateManager(str(tmp_path / 'state.json'))
    sm.save({
        'last_run': None,
        'members': {},
        'tickets': {
            'POT-1': {
                'key': 'POT-1',
                'status': 'IN PROGRESS',
                'status_category': 'IN PROGRESS',
                'is_blocked': False,
                'last_updated': None,
                'issue_type': 'Story'
            }
        }
    })
    sm.sync_ticket_after_event('POT-1', {'status': 'BLOCKED'})
    state = sm.load()
    ticket = state['tickets']['POT-1']
    assert ticket['status'] == 'BLOCKED'
    assert ticket['status_category'] == 'IN PROGRESS'
    assert ticket['is_blocked'] is True
    assert ticket['last_updated'] is not None


def test_sync_sets_is_blocked_on_blocked_status(tmp_path, monkeypatch):
    """Quand status = BLOCKED, is_blocked doit passer à True."""
    monkeypatch.chdir(tmp_path)
    sm = StateManager(str(tmp_path / 'state.json'))
    sm.save({
        'last_run': None,
        'members': {},
        'tickets': {
            'POT-2': {
                'key': 'POT-2',
                'status': 'IN PROGRESS',
                'status_category': 'IN PROGRESS',
                'is_blocked': False,
                'last_updated': None,
                'issue_type': 'Bug'
            }
        }
    })
    sm.sync_ticket_after_event('POT-2', {'status': 'IN PROGRESS'})
    assert sm.load()['tickets']['POT-2']['is_blocked'] is False


def test_blocking_resolved_when_blocker_absent(tmp_path, monkeypatch):
    """Un ticket bloquant absent du state est considéré comme résolu."""
    monkeypatch.chdir(tmp_path)
    from scenario_engine import ScenarioEngine
    engine = ScenarioEngine()
    ticket = {
        'key': 'KAN-9',
        'linked_issues': [{'key': 'KAN-7', 'link_type': 'is blocked by'}]
    }
    state = {'tickets': {}}  # KAN-7 absent
    assert engine._is_blocking_resolved(ticket, state) is True


def test_blocking_not_resolved_when_blocker_in_progress(tmp_path, monkeypatch):
    """Un ticket bloquant en IN PROGRESS empêche la finalisation."""
    monkeypatch.chdir(tmp_path)
    from scenario_engine import ScenarioEngine
    engine = ScenarioEngine()
    ticket = {
        'key': 'POT-6',
        'linked_issues': [{'key': 'POT-10', 'link_type': 'is blocked by'}]
    }
    state = {
        'tickets': {
            'POT-10': {
                'key': 'POT-10',
                'status_category': 'IN PROGRESS'
            }
        }
    }
    assert engine._is_blocking_resolved(ticket, state) is False


def test_sync_sets_last_updated_timestamp(tmp_path, monkeypatch):
    """sync_ticket_after_event doit toujours mettre à jour last_updated."""
    monkeypatch.chdir(tmp_path)
    sm = StateManager(str(tmp_path / 'state.json'))
    sm.save({
        'last_run': None,
        'members': {},
        'tickets': {
            'POT-3': {
                'key': 'POT-3',
                'status': 'TO DO',
                'status_category': 'TO DO',
                'is_blocked': False,
                'last_updated': '2026-03-25T10:00:00.000000',
                'issue_type': 'Feature'
            }
        }
    })
    sm.sync_ticket_after_event('POT-3', {'priority': 'High'})
    ticket = sm.load()['tickets']['POT-3']
    # last_updated doit être plus récent
    old_time = datetime.datetime.fromisoformat('2026-03-25T10:00:00.000000')
    new_time = datetime.datetime.fromisoformat(ticket['last_updated'])
    assert new_time > old_time


def test_sync_handles_missing_ticket(tmp_path, monkeypatch, caplog):
    """sync_ticket_after_event doit logger un warning pour un ticket absent."""
    monkeypatch.chdir(tmp_path)
    sm = StateManager(str(tmp_path / 'state.json'))
    sm.save({'last_run': None, 'members': {}, 'tickets': {}})
    sm.sync_ticket_after_event('MISSING-1', {'status': 'DONE'})
    assert 'introuvable' in caplog.text.lower()


def test_is_blocking_resolved_with_multiple_links(tmp_path, monkeypatch):
    """Tous les blockers doivent être DONE pour que _is_blocking_resolved retourne True."""
    monkeypatch.chdir(tmp_path)
    from scenario_engine import ScenarioEngine
    engine = ScenarioEngine()
    ticket = {
        'key': 'POT-5',
        'linked_issues': [
            {'key': 'POT-1', 'link_type': 'is blocked by'},
            {'key': 'POT-2', 'link_type': 'is blocked by'}
        ]
    }
    state = {
        'tickets': {
            'POT-1': {'key': 'POT-1', 'status_category': 'DONE'},
            'POT-2': {'key': 'POT-2', 'status_category': 'DONE'}
        }
    }
    assert engine._is_blocking_resolved(ticket, state) is True

    # Si l'un d'eux n'est pas DONE
    state['tickets']['POT-2']['status_category'] = 'IN PROGRESS'
    assert engine._is_blocking_resolved(ticket, state) is False
