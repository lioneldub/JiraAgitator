import pytest
from scenario_engine import ScenarioEngine


def test_build_event_includes_member_role():
    """L'event doit contenir member_role pour les prompts IA."""
    engine = ScenarioEngine()
    scenario = {'type': 'add_comment'}
    state = {
        'members': {
            'alice_m': {'availability': 'available', 'team_id': 'phoenix'}
        },
        'tickets': {
            'PROJ-1': {'key': 'PROJ-1', 'summary': 'Test', 'status': 'In Progress',
                       'assignee_id': 'alice_m', 'team_id': 'phoenix', 'is_blocked': False}
        }
    }
    teams_cfg = {'teams': [{'id': 'phoenix', 'members': [
        {'id': 'alice_m', 'display_name': 'Alice Martin', 'role': 'lead'}
    ]}]}
    event = engine.build_event(scenario, state, teams_cfg)
    assert event is not None
    assert 'member_role' in event
    assert event['member_role'] == 'lead'
