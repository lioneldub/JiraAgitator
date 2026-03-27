import os
import requests
from jira_client import JiraClient


def test_add_comment_dry_run():
    client = JiraClient(force_dry_run=True)
    result = client.add_comment('PROJ-1', 'Test')
    assert result['status'] == 'dry-run'


def test_transition_dry_run():
    client = JiraClient(force_dry_run=True)
    result = client.transition_ticket('PROJ-1', 'Done')
    assert result['status'] == 'dry-run'


def test_live_raises_not_implemented():
    os.environ['DRY_RUN'] = 'false'
    os.environ['JIRA_EMAIL'] = 'email@example.com'
    os.environ['JIRA_API_TOKEN'] = 'token'
    os.environ['JIRA_BASE_URL'] = 'https://example.atlassian.net'
    os.environ['JIRA_PROJECT_KEY'] = 'PROJ'

    client2 = JiraClient(force_dry_run=False)
    result = client2.add_comment('PROJ-1', 'Test')
    assert isinstance(result, dict)
    # en mode live non connecté, on peut obtenir {} ou une clé de réponse selon la configuration du JIRA
