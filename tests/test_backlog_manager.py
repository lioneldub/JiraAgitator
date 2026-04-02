import pytest
from unittest.mock import MagicMock, patch


def test_check_and_replenish_creates_stories_when_below_threshold(
        tmp_path, monkeypatch):
    """Doit créer des Stories si moins de MIN_TODO_TICKETS tickets en TO DO."""
    monkeypatch.setenv('MIN_TODO_TICKETS', '3')
    monkeypatch.setenv('MIN_ACTIVE_EPICS', '2')
    monkeypatch.chdir(tmp_path)

    from state_manager import StateManager
    sm = StateManager(str(tmp_path / 'state.json'))
    sm.save({
        'last_run': None,
        'members': {
            'lionel_d': {'role': 'lead', 'availability': 'available',
                         'team_ids': ['phoenix'], 'jira_account_id': '123'}
        },
        'tickets': {
            'POT-1': {'key': 'POT-1', 'issue_type': 'Epic',
                      'status_category': 'IN PROGRESS', 'team_id': 'phoenix'},
            'POT-2': {'key': 'POT-2', 'issue_type': 'Epic',
                      'status_category': 'IN PROGRESS', 'team_id': 'phoenix'},
            # Seulement 1 ticket TO DO — sous le seuil de 3
            'POT-3': {'key': 'POT-3', 'issue_type': 'Story',
                      'status_category': 'TO DO', 'team_id': 'phoenix'},
        }
    })

    mock_jira = MagicMock()
    mock_jira.create_issue.return_value = {'key': 'POT-99'}
    mock_ai = MagicMock()
    teams_cfg = {'teams': [{'id': 'phoenix', 'jira_project_key': 'POT',
                             'members': []}]}

    from backlog_manager import check_and_replenish
    result = check_and_replenish(
        ['POT'], mock_jira, sm, mock_ai, teams_cfg, dry_run=False
    )
    # Doit avoir créé 2 Stories (3 - 1 existante)
    assert result['stories_created'] == 2


def test_no_creation_when_above_threshold(tmp_path, monkeypatch):
    """Ne doit rien créer si le seuil est atteint."""
    monkeypatch.setenv('MIN_TODO_TICKETS', '2')
    monkeypatch.setenv('MIN_ACTIVE_EPICS', '1')
    monkeypatch.chdir(tmp_path)

    from state_manager import StateManager
    sm = StateManager(str(tmp_path / 'state.json'))
    sm.save({
        'last_run': None, 'members': {},
        'tickets': {
            'POT-1': {'key': 'POT-1', 'issue_type': 'Epic',
                      'status_category': 'IN PROGRESS', 'team_id': 'phoenix'},
            'POT-2': {'key': 'POT-2', 'issue_type': 'Story',
                      'status_category': 'TO DO', 'team_id': 'phoenix'},
            'POT-3': {'key': 'POT-3', 'issue_type': 'Story',
                      'status_category': 'TO DO', 'team_id': 'phoenix'},
            'POT-4': {'key': 'POT-4', 'issue_type': 'Story',
                      'status_category': 'TO DO', 'team_id': 'phoenix'},
        }
    })

    mock_jira = MagicMock()
    mock_ai = MagicMock()
    teams_cfg = {'teams': [{'id': 'phoenix', 'jira_project_key': 'POT',
                             'members': []}]}

    from backlog_manager import check_and_replenish
    result = check_and_replenish(
        ['POT'], mock_jira, sm, mock_ai, teams_cfg, dry_run=False
    )
    assert result['stories_created'] == 0
    mock_jira.create_issue.assert_not_called()