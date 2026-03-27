# Prompt GitHub Copilot — Phase 3 : Corrections pré-live + connexion Jira réelle
# Jira Activity Simulator — Suite de la phase 2

---

## Contexte et état actuel

Phase 1 et 2 terminées et validées :
- `python main.py --events 5 --dry-run` fonctionne, 9 tests passent
- Provider pattern en place (stub / gemini / groq)
- JiraClient avec méthodes HTTP live squelettées mais non validées
- `bootstrap_state.py` créé mais jamais testé en run réel
- Le fichier `.env` a été créé manuellement depuis `.env.example`

**Avant de passer en mode live, 4 bugs identifiés doivent être corrigés.**
La phase 3 les corrige en premier, puis connecte le simulateur à Jira Cloud réel.

---

## PARTIE 1 — Corrections avant live (obligatoires)

### 1.1 Corriger le state désynchronisé dans la boucle de `scheduler.py`

**Problème** : `state` est chargé une seule fois avant la boucle. Après une mutation
(`change_status`, `block_ticket`…), le dict en mémoire diverge du JSON sur disque.
Seul `change_assignee` recharge — les autres branches ne le font pas.

**Correction** : recharger `state` en début de chaque itération :

```python
for _ in range(n_events):
    state = state_manager.load()          # ← recharger à chaque tour
    scenario = scenario_engine.pick_scenario()
    event = scenario_engine.build_event(scenario, state, teams_config)
    ...
```

Supprimer le `state = state_manager.load()` localisé dans la branche
`change_assignee` — il devient redondant.

### 1.2 Corriger le retry manquant sur HTTP 429 dans `jira_client.py`

**Problème** : `_handle_response` sur 429 fait `time.sleep(60)` puis `return {}`
sans retry. L'événement est perdu silencieusement et compté comme exécuté.

**Correction** : `_handle_response` doit accepter un callable optionnel `retry_fn`
et le rappeler après le sleep, ou plus simplement lever une exception catchée
dans le scheduler :

```python
elif response.status_code == 429:
    logger.warning("Rate limit Jira — attente 60s puis retry")
    import time
    time.sleep(60)
    # On lève pour que le scheduler incrémente skipped, pas executed
    raise RuntimeError("Jira 429 RateLimit — événement non exécuté")
```

Dans `scheduler.py`, le `except Exception` existant capturera cette erreur et
incrémentera `skipped` — comportement correct.

### 1.3 Ajouter `member_role` dans le dict event de `scenario_engine.py`

**Problème** : les providers Gemini et Groq utilisent `{role}` dans leur prompt
contextuel pour personnaliser le ton (lead vs dev vs qa), mais le dict `event`
ne porte pas ce champ — il est absent du `ScenarioEngine`.

**Correction** : dans `scenario_engine.py`, enrichir le dict event retourné par
`build_event` :

```python
return {
    'type': scenario_type,
    'team_id': team_id,
    'member_id': member['id'],
    'member_name': member['display_name'],
    'member_role': member.get('role', 'dev'),     # ← ajouter cette ligne
    'ticket_key': ticket['key'],
    'ticket_summary': ticket.get('summary'),
    'context': {
        'current_status': ticket.get('status'),
        'is_blocked': ticket.get('is_blocked', False)
    },
    'ai_content': None
}
```

Faire de même pour le bloc absence/retour (même structure, `ticket_key: None`).

Vérifier ensuite que `gemini_provider.py` et `groq_provider.py` utilisent bien
`event.get('member_role', 'dev')` dans la construction du prompt. Si ce n'est pas
le cas, mettre à jour le prompt des deux providers :

```python
role = event.get('member_role', 'dev')
member_name = event.get('member_name', 'Un membre')
team_id = event.get('team_id', 'l\'équipe')
ticket_key = event.get('ticket_key', '')
ticket_summary = event.get('ticket_summary', '')
current_status = event.get('context', {}).get('current_status', '')

prompt = f"""Tu simules {member_name}, {role} dans l'équipe Scrum "{team_id}".
Tu travailles sur le ticket "{ticket_key} — {ticket_summary}" (statut actuel : {current_status}).
Action demandée : {_describe_event_type(event['type'])}

Génère un message court (2-4 phrases maximum) en français, naturel et professionnel,
comme si tu étais vraiment ce développeur dans son outil de ticketing.
Ne commence pas par "Je" — varie les formulations.
Réponds uniquement avec le message, sans introduction ni explication."""
```

Ajouter une fonction privée `_describe_event_type(event_type: str) -> str` dans
chaque provider qui retourne une description française du type d'événement :

```python
def _describe_event_type(self, event_type: str) -> str:
    descriptions = {
        'add_comment':         'Ajouter un commentaire de suivi sur ce ticket',
        'change_status':       'Signaler l\'avancement ou la complétion du ticket',
        'block_ticket':        'Expliquer un blocage technique ou organisationnel',
        'change_assignee':     'Justifier brièvement la réassignation',
        'set_absence':         'Annoncer une absence et le transfert des tickets',
        'return_from_absence': 'Signaler le retour et la reprise des activités',
        'add_subtask':         'Décrire la sous-tâche créée et son périmètre',
    }
    return descriptions.get(event_type, 'Commenter ce ticket')
```

### 1.4 Brancher le mapping `member_id → jira_account_id` dans `jira_client.py`

**Problème** : `assign_ticket` envoie `member_id` ("alice_m") comme `accountId`
vers Jira Cloud — l'API retournera 400. Le champ `jira_account_id` existe dans
`teams.yaml` mais n'est jamais chargé par le `JiraClient`.

**Correction** : dans `JiraClient.__init__`, charger `teams.yaml` et construire
un dict de résolution :

```python
from pathlib import Path
import yaml

# Après les autres initialisations dans __init__
self._account_id_map: dict[str, str] = {}
teams_path = Path('config/teams.yaml')
if teams_path.exists():
    with teams_path.open('r', encoding='utf-8') as f:
        teams_cfg = yaml.safe_load(f)
    for team in teams_cfg.get('teams', []):
        for member in team.get('members', []):
            mid = member.get('id', '')
            aid = member.get('jira_account_id', '')
            if mid and aid:
                self._account_id_map[mid] = aid
```

Dans `assign_ticket` :
```python
def assign_ticket(self, ticket_key: str, account_id: str) -> dict:
    """Réassigne le ticket. Résout member_id → jira_account_id si nécessaire."""
    resolved_id = self._account_id_map.get(account_id, account_id)
    if self.dry_run:
        return self._dry_log('change_assignee', ticket_key,
                             f'assign to {account_id} (accountId: {resolved_id})')
    ...
    # utiliser resolved_id dans le body de la requête
```

### 1.5 Ajouter `pytest.importorskip` dans `tests/test_providers.py`

**Problème** : si `google-generativeai` ou `groq` ne sont pas installés,
le fichier de test crashe à l'import avant d'arriver aux assertions.

**Correction** : en haut de `tests/test_providers.py` :

```python
import pytest

# Skip automatiquement si les packages optionnels sont absents
genai = pytest.importorskip(
    "google.generativeai",
    reason="google-generativeai non installé — tests Gemini ignorés"
)
groq_pkg = pytest.importorskip(
    "groq",
    reason="groq non installé — tests Groq ignorés"
)
```

Vérifier que `python -m pytest -v` passe toujours avec 9+ tests après ces corrections.

---

## PARTIE 2 — Connexion Jira Cloud réelle

### 2.1 Script de vérification de connexion `check_jira_connection.py`

Avant d'activer le mode live dans le simulateur, créer un script de diagnostic
autonome qui vérifie que les credentials `.env` sont valides :

```python
"""
Vérifie la connexion Jira Cloud et liste les infos du projet.
Usage : python check_jira_connection.py
Ne modifie rien — lecture seule.
"""
import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

base_url   = os.getenv('JIRA_BASE_URL', '').rstrip('/')
email      = os.getenv('JIRA_EMAIL', '')
api_token  = os.getenv('JIRA_API_TOKEN', '')
project_key = os.getenv('JIRA_PROJECT_KEY', 'PROJ')

if not all([base_url, email, api_token]):
    print("[ERREUR] JIRA_BASE_URL, JIRA_EMAIL ou JIRA_API_TOKEN manquant dans .env")
    exit(1)

credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
headers = {
    "Authorization": f"Basic {credentials}",
    "Accept": "application/json"
}

checks = [
    ("Authentification",      f"{base_url}/rest/api/3/myself"),
    ("Projet",                f"{base_url}/rest/api/3/project/{project_key}"),
    ("Tickets ouverts (JQL)", f"{base_url}/rest/api/3/search?jql=project={project_key}+AND+statusCategory!=Done&maxResults=5"),
]

all_ok = True
for label, url in checks:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if label == "Authentification":
                print(f"[OK] {label} — connecté en tant que {data.get('displayName', '?')}")
            elif label == "Projet":
                print(f"[OK] {label} — {data.get('name','?')} ({project_key})")
            else:
                total = data.get('total', 0)
                print(f"[OK] {label} — {total} ticket(s) ouvert(s)")
        else:
            print(f"[ERREUR] {label} — HTTP {r.status_code}: {r.text[:120]}")
            all_ok = False
    except Exception as e:
        print(f"[ERREUR] {label} — {e}")
        all_ok = False

print()
if all_ok:
    print("Connexion Jira validée — tu peux passer DRY_RUN=false dans .env")
else:
    print("Corriger les erreurs ci-dessus avant de passer en mode live")
```

### 2.2 Script de récupération des `accountId` Jira : `fetch_account_ids.py`

Pour remplir les `jira_account_id` dans `teams.yaml`, créer un script qui
interroge Jira et affiche les accountId des membres :

```python
"""
Affiche les accountId Jira des membres de l'équipe pour compléter teams.yaml.
Usage : python fetch_account_ids.py
"""
import os
import base64
import requests
import yaml
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

base_url  = os.getenv('JIRA_BASE_URL', '').rstrip('/')
email     = os.getenv('JIRA_EMAIL', '')
api_token = os.getenv('JIRA_API_TOKEN', '')

credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}

with Path('config/teams.yaml').open('r', encoding='utf-8') as f:
    teams_cfg = yaml.safe_load(f)

print("Recherche des accountId Jira pour chaque membre :\n")
for team in teams_cfg.get('teams', []):
    print(f"  Équipe : {team['name']}")
    for member in team.get('members', []):
        name = member['display_name']
        r = requests.get(
            f"{base_url}/rest/api/3/user/search",
            headers=headers,
            params={"query": name, "maxResults": 3},
            timeout=10
        )
        if r.status_code == 200 and r.json():
            for user in r.json():
                print(f"    {name} → accountId: {user['accountId']}  "
                      f"(email: {user.get('emailAddress','?')})")
        else:
            print(f"    {name} → non trouvé (HTTP {r.status_code})")
    print()

print("Copie les accountId dans config/teams.yaml sous le champ jira_account_id.")
```

### 2.3 Activer le mode live dans `jira_client.py` — vérification complète

Lire le fichier `jira_client.py` actuel et vérifier que chaque méthode live est
correctement implémentée selon les specs suivantes. Corriger ce qui manque.

#### `add_comment` — corps en format Atlassian Document Format (ADF)
```python
def add_comment(self, ticket_key: str, body: str) -> dict:
    if self.dry_run:
        return self._dry_log('add_comment', ticket_key, f'"{body[:80]}..."')
    url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/comment"
    payload = {
        "body": {
            "type": "doc", "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": body}]
            }]
        }
    }
    r = requests.post(url, headers=self._get_auth_headers(), json=payload, timeout=15)
    return self._handle_response(r, f"add_comment({ticket_key})")
```

#### `transition_ticket` — résolution du transition_id via GET
```python
def _get_transition_id(self, ticket_key: str, target_status: str) -> str | None:
    url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/transitions"
    r = requests.get(url, headers=self._get_auth_headers(), timeout=10)
    if r.status_code != 200:
        return None
    for t in r.json().get('transitions', []):
        if t.get('to', {}).get('name', '').lower() == target_status.lower():
            return t['id']
    logger.warning("Transition '%s' non trouvée pour %s", target_status, ticket_key)
    return None

def transition_ticket(self, ticket_key: str, new_status: str) -> dict:
    if self.dry_run:
        return self._dry_log('change_status', ticket_key,
                             f"transition to '{new_status}'")
    transition_id = self._get_transition_id(ticket_key, new_status)
    if not transition_id:
        logger.warning("Transition ignorée — ID introuvable pour '%s'", new_status)
        return {}
    url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/transitions"
    r = requests.post(url, headers=self._get_auth_headers(),
                      json={"transition": {"id": transition_id}}, timeout=15)
    return self._handle_response(r, f"transition_ticket({ticket_key}→{new_status})")
```

#### `get_tickets_for_project` — normalisation au format state.json
```python
def get_tickets_for_project(self) -> list[dict]:
    if self.dry_run:
        return [
            {'key': 'PROJ-1', 'summary': 'Setup CI pipeline',
             'status': 'In Progress', 'assignee_id': 'alice_m',
             'team_id': 'phoenix', 'is_blocked': False},
            {'key': 'PROJ-2', 'summary': 'Implement authentication',
             'status': 'To Do', 'assignee_id': 'bob_d',
             'team_id': 'phoenix', 'is_blocked': False},
        ]
    url = (f"{self.base_url}/rest/api/3/search"
           f"?jql=project={self.project_key}+AND+statusCategory!=Done"
           f"&maxResults=50&fields=summary,status,assignee")
    r = requests.get(url, headers=self._get_auth_headers(), timeout=15)
    data = self._handle_response(r, "get_tickets_for_project")
    tickets = []
    for issue in data.get('issues', []):
        fields = issue.get('fields', {})
        assignee = fields.get('assignee') or {}
        tickets.append({
            'key': issue['key'],
            'summary': fields.get('summary', ''),
            'status': fields.get('status', {}).get('name', 'To Do'),
            'assignee_id': assignee.get('accountId', ''),
            'team_id': self.project_key.lower(),
            'is_blocked': False
        })
    return tickets
```

---

## PARTIE 3 — Amélioration de `bootstrap_state.py`

Le fichier existe mais n'a jamais été testé. Le corriger et le compléter :

```python
"""
Peuple state.json depuis les vrais tickets Jira (ou fixtures en dry-run).
Usage : python bootstrap_state.py [--project PROJ] [--dry-run]
"""
import os
import argparse
import yaml
import logging
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

from jira_client import JiraClient
from state_manager import StateManager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')


def bootstrap(project_key: str, force_dry_run: bool = False) -> None:
    """Reconstruit state.json depuis Jira ou les fixtures dry-run."""
    jira = JiraClient(force_dry_run=force_dry_run)
    state_mgr = StateManager()

    logger.info("Récupération des tickets pour le projet %s...", project_key)
    tickets_raw = jira.get_tickets_for_project()

    with open('config/teams.yaml', 'r', encoding='utf-8') as f:
        teams_config = yaml.safe_load(f)

    members: dict = {}
    for team in teams_config.get('teams', []):
        for m in team.get('members', []):
            members[m['id']] = {
                'availability': m.get('availability', 'available'),
                'current_tickets': [],
                'team_id': team['id'],
                'display_name': m.get('display_name', ''),
                'role': m.get('role', 'dev')
            }

    tickets: dict = {}
    for t in tickets_raw:
        tickets[t['key']] = t

    state = {
        'last_run': None,
        'members': members,
        'tickets': tickets
    }
    state_mgr.save(state)
    logger.info("Bootstrap terminé — %d ticket(s), %d membre(s) chargés",
                len(tickets), len(members))
    logger.info("State sauvegardé dans state.json")

    # Afficher un résumé lisible
    for key, ticket in tickets.items():
        logger.info("  %s | %-30s | %s | %s",
                    key,
                    ticket.get('summary', '')[:30],
                    ticket.get('status', ''),
                    ticket.get('assignee_id', 'non assigné'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bootstrap state depuis Jira')
    parser.add_argument('--project',
                        default=os.getenv('JIRA_PROJECT_KEY', 'PROJ'),
                        help='Clé du projet Jira')
    parser.add_argument('--dry-run', action='store_true',
                        help='Utiliser les fixtures (pas d\'appel Jira réel)')
    args = parser.parse_args()
    bootstrap(args.project, force_dry_run=args.dry_run)
```

---

## PARTIE 4 — Tests à ajouter / mettre à jour

### Mettre à jour `tests/test_providers.py`

Ajouter `pytest.importorskip` en haut (voir correction 1.5) et ajouter un test
qui vérifie que `_describe_event_type` couvre tous les types de scénarios :

```python
def test_stub_provider_describe_event_type_coverage():
    """Vérifie que tous les types de scénarios ont une description."""
    from providers.gemini_provider import GeminiProvider
    p = GeminiProvider.__new__(GeminiProvider)  # sans appel __init__
    types = ['add_comment', 'change_status', 'block_ticket',
             'change_assignee', 'set_absence', 'return_from_absence', 'add_subtask']
    for t in types:
        desc = p._describe_event_type(t)
        assert isinstance(desc, str) and len(desc) > 5
```

### Ajouter `tests/test_bootstrap.py`

```python
import pytest
from unittest.mock import patch, MagicMock
from bootstrap_state import bootstrap


def test_bootstrap_dry_run_creates_state(tmp_path, monkeypatch):
    """Bootstrap en dry-run doit créer un state.json valide."""
    import json
    monkeypatch.chdir(tmp_path)
    # Copier les fichiers de config nécessaires
    import shutil, pathlib
    src = pathlib.Path(__file__).parent.parent
    (tmp_path / 'config').mkdir()
    shutil.copy(src / 'config' / 'teams.yaml', tmp_path / 'config' / 'teams.yaml')

    bootstrap(project_key='PROJ', force_dry_run=True)

    state_file = tmp_path / 'state.json'
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert 'members' in state
    assert 'tickets' in state
    assert len(state['members']) > 0
    assert len(state['tickets']) > 0
```

### Ajouter `tests/test_scenario_engine_role.py`

```python
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
```

---

## PARTIE 5 — `pyproject.toml` minimal pour verrouiller l'environnement

Créer `pyproject.toml` à la racine (ne remplace pas `requirements.txt`) :

```toml
[project]
name = "jira-simulator"
version = "0.3.0"
requires-python = ">=3.11"
description = "Simulateur d'activité Jira Cloud avec IA"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
log_cli = true
log_cli_level = "WARNING"
```

---

## Règles de code (identiques aux phases précédentes)

- Python 3.11+, type hints, docstrings en français
- `logging` uniquement — pas de `print` sauf dans `_dry_log` de `JiraClient`
- `load_dotenv()` en première instruction de tout point d'entrée
- Chemins avec `pathlib.Path`
- Erreurs HTTP catchées et loggées — 401/403 lèvent, 404 retourne `{}`,
  429 lève `RuntimeError` (capturé par le scheduler)

---

## Ordre d'exécution recommandé pour Copilot

1. Corrections 1.1 à 1.5 (Partie 1) → `python -m pytest -v` doit toujours passer
2. Créer `check_jira_connection.py` et `fetch_account_ids.py` (Partie 2.1 et 2.2)
3. Vérifier et compléter les méthodes live de `jira_client.py` (Partie 2.3)
4. Mettre à jour `bootstrap_state.py` (Partie 3)
5. Ajouter les nouveaux tests (Partie 4)
6. Créer `pyproject.toml` (Partie 5)
7. Lancer `python -m pytest -v` — tous les tests doivent passer

---

## Validation finale attendue

```bash
# 1. Vérifier que les corrections sont actives
python -m pytest -v
# Attendu : 12+ tests passent, 0 échoue

# 2. Vérifier la connexion Jira (credentials .env requis)
python check_jira_connection.py
# Attendu :
# [OK] Authentification — connecté en tant que Prénom Nom
# [OK] Projet — Mon Projet (PROJ)
# [OK] Tickets ouverts (JQL) — N ticket(s) ouvert(s)
# Connexion Jira validée — tu peux passer DRY_RUN=false dans .env

# 3. Récupérer les accountId pour compléter teams.yaml
python fetch_account_ids.py
# Attendu : liste des membres avec leur accountId Jira Cloud

# 4. Bootstrap depuis Jira réel (après avoir rempli DRY_RUN=false dans .env)
python bootstrap_state.py --project PROJ
# Attendu : state.json peuplé avec les vrais tickets Jira

# 5. Simulation en dry-run après bootstrap
python main.py --events 5 --dry-run
# Attendu : même comportement qu'avant, state.json mis à jour

# 6. Bootstrap en dry-run (sans connexion Jira)
python bootstrap_state.py --dry-run
# Attendu : state.json peuplé avec les fixtures
```

---

## Note importante sur le passage en mode live

Ne pas encore passer `DRY_RUN=false` dans `.env` pour le run principal.
La phase 3 se termine quand `check_jira_connection.py` valide la connexion
et que `bootstrap_state.py` peuple le state depuis Jira réel.
Le passage `DRY_RUN=false` dans `main.py` sera l'objet d'une validation
manuelle explicite en phase 4.
