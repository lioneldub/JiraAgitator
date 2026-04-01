import pytest
from scenario_engine import ScenarioEngine

TEAMS_CFG = {'teams': [
    {'id': 'phoenix', 'members': [
        {'id': 'paul', 'display_name': 'Paul', 'role': 'DEV'},
        {'id': 'gala', 'display_name': 'Gala', 'role': 'QA'},
        {'id': 'lionel_d', 'display_name': 'Lionel', 'role': 'lead'},
    ]}
]}

BASE_STATE = {
    'members': {
        'paul':     {'availability': 'available', 'team_ids': ['phoenix'],
                     'role': 'DEV', 'display_name': 'Paul'},
        'gala':     {'availability': 'available', 'team_ids': ['phoenix'],
                     'role': 'QA', 'display_name': 'Gala'},
        'lionel_d': {'availability': 'available', 'team_ids': ['phoenix', 'nebula'],
                     'role': 'lead', 'display_name': 'Lionel'},
    },
    'tickets': {
        'POT-19': {'key': 'POT-1', 'summary': 'Auth epic',
                  'issue_type': 'Epic', 'status': 'IN PROGRESS',
                  'status_category': 'IN PROGRESS', 'priority': 'High',
                  'assignee_id': 'lionel_d', 'team_id': 'phoenix',
                  'epic_key': None, 'subtask_keys': [], 'linked_issues': [],
                  'is_blocked': False},
        'POT-6': {'key': 'POT-2', 'summary': 'Implement OAuth',
                  'issue_type': 'Story', 'status': 'IN PROGRESS',
                  'status_category': 'IN PROGRESS', 'priority': 'High',
                  'assignee_id': 'paul', 'team_id': 'phoenix',
                  'epic_key': 'POT-1', 'subtask_keys': [], 'linked_issues': [],
                  'is_blocked': False},
        'POT-10': {'key': 'POT-3', 'summary': 'Login bug',
                  'issue_type': 'Bug', 'status': 'IN REVIEW',
                  'status_category': 'IN PROGRESS', 'priority': 'High',
                  'assignee_id': 'gala', 'team_id': 'phoenix',
                  'epic_key': None, 'subtask_keys': [], 'linked_issues': [],
                  'is_blocked': False},
    }
}


def test_demande_review_only_dev_or_lead():
    engine = ScenarioEngine()
    scenario = next(s for s in engine.scenarios if s['id'] == 'demande_review')
    state = {**BASE_STATE, 'members': {'gala': BASE_STATE['members']['gala']}}
    event = engine.build_event(scenario, state, TEAMS_CFG)
    assert event is None


def test_finalisation_only_qa_ba_lead():
    engine = ScenarioEngine()
    scenario = next(s for s in engine.scenarios if s['id'] == 'finalisation')
    state = {**BASE_STATE}
    state['tickets']['POT-10']['status'] = 'IN REVIEW'
    state = {**state, 'members': {'paul': BASE_STATE['members']['paul']}}
    event = engine.build_event(scenario, state, TEAMS_CFG)
    assert event is None


def test_event_contains_issue_type():
    engine = ScenarioEngine()
    scenario = next(s for s in engine.scenarios if s['id'] == 'mise_a_jour_progression')
    event = engine.build_event(scenario, BASE_STATE, TEAMS_CFG)
    assert event is not None
    assert 'issue_type' in event
    assert event['issue_type'] in ['Story', 'Bug', 'Task', 'Epic', 'Sub-task']


def test_blocage_requires_ai_comment_flag():
    engine = ScenarioEngine()
    scenario = next(s for s in engine.scenarios if s['id'] == 'blocage')
    event = engine.build_event(scenario, BASE_STATE, TEAMS_CFG)
    if event:
        assert event['context'].get('requires_ai_comment') is True
