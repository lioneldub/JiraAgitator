from scenario_engine import ScenarioEngine


BASE_STATE = {
    'members': {
        'paul': {'availability': 'available', 'team_ids': ['phoenix'],
                 'role': 'DEV', 'display_name': 'Paul'},
    },
    'tickets': {
        # POT récemment touché
        'POT-1': {'key': 'POT-1', 'issue_type': 'Story',
                  'status': 'IN PROGRESS', 'status_category': 'IN PROGRESS',
                  'priority': 'Medium', 'team_id': 'phoenix',
                  'epic_key': None, 'subtask_keys': [], 'linked_issues': [],
                  'is_blocked': False,
                  'last_updated': '2026-04-01T14:00:00'},
        # KAN jamais touché
        'KAN-1': {'key': 'KAN-1', 'issue_type': 'Story',
                  'status': 'IN PROGRESS', 'status_category': 'IN PROGRESS',
                  'priority': 'Medium', 'team_id': 'phoenix',
                  'epic_key': None, 'subtask_keys': [], 'linked_issues': [],
                  'is_blocked': False,
                  'last_updated': None},
    }
}

TEAMS_CFG = {'teams': [{'id': 'phoenix', 'members': [
    {'id': 'paul', 'display_name': 'Paul', 'role': 'DEV'}
]}]}


def test_pick_project_favors_least_active():
    """Le projet le moins récemment actif doit être favorisé."""
    engine = ScenarioEngine()
    candidates = list(BASE_STATE['tickets'].values())
    balanced = engine._pick_project_balanced(candidates, BASE_STATE)
    # KAN-1 jamais touché → doit être sélectionné
    assert all(t['key'].startswith('KAN') for t in balanced)


def test_pick_ticket_weighted_favors_old():
    """Un ticket jamais touché doit avoir plus de poids qu'un ticket récent."""
    engine = ScenarioEngine()
    candidates = list(BASE_STATE['tickets'].values())
    # Lancer 100 fois et vérifier que KAN-1 est sélectionné plus souvent
    kan_count = sum(
        1 for _ in range(100)
        if engine._pick_ticket_weighted(candidates)['key'] == 'KAN-1'
    )
    # KAN-1 doit être choisi dans la grande majorité des cas
    assert kan_count > 70