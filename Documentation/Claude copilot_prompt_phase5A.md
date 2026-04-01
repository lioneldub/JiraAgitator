# Prompt GitHub Copilot — Phase 5A : Fondations scénarios enrichis
# Jira Activity Simulator — Refactoring état + 7 scénarios de base

---

## Contexte et état actuel

- Phases 1 à 4 terminées — run live validé sur Jira Cloud avec stub IA
- Project POT (Potemkine) vient d'être peuplé via import CSV :
  4 Epics, ~20 Stories, 5 Bugs, 4 Tasks — 2 équipes (phoenix / nebula)
- Un champ custom "Équipe" a été ajouté dans Jira pour associer un ticket à une équipe
- teams.yaml mis à jour avec les vrais jira_account_id (Lionel, Fatou, Gala, Paul, Pierre)
- Même membre peut appartenir à plusieurs équipes (Lionel est Lead dans les deux)

**Objectif de cette phase** : enrichir le modèle de données pour supporter
les types de tickets, la hiérarchie Epic/Story, les priorités, et implémenter
les 7 scénarios les plus fréquents avec leurs garde-fous métier de base.

---

## Référence — Statuts Jira du projet POT

```
Catégorie TO DO     : IDEA, TO DO
Catégorie IN PROGRESS : IN PROGRESS, IN REVIEW, BLOCKED
Catégorie DONE      : DONE, CANCELLED
```

Transitions "Any to Any" autorisées dans Jira, mais le simulateur pondère
les choix selon l'état courant (logique métier dans ScenarioEngine).

---

## Référence — Rôles et permissions métier

```
lead  : peut tout faire
DEV   : peut commenter, transition vers IN REVIEW, créer bugs/sous-tâches
BA    : peut commenter, mettre à jour descriptions, créer Stories, valider (DONE)
QA    : peut commenter, valider (DONE), créer bugs, bloquer
```

---

## PARTIE 1 — Enrichissement du modèle state.json

### 1.1 Nouveau format de ticket dans state.json

Remplacer le format actuel par un format enrichi qui supporte
les types, la hiérarchie et les métadonnées nécessaires aux scénarios :

```json
{
  "last_run": null,
  "members": {
    "lionel_d": {
      "availability": "available",
      "team_ids": ["phoenix", "nebula"],
      "display_name": "Lionel Dubois",
      "role": "lead",
      "jira_account_id": "5d3b1c6375218c0c20adb6c1"
    }
  },
  "tickets": {
    "POT-1": {
      "key": "POT-1",
      "summary": "Refonte du module d'authentification",
      "issue_type": "Epic",
      "status": "IN PROGRESS",
      "status_category": "IN PROGRESS",
      "priority": "High",
      "assignee_id": "lionel_d",
      "team_id": "phoenix",
      "epic_key": null,
      "parent_key": null,
      "subtask_keys": [],
      "linked_issues": [],
      "story_points": null,
      "is_blocked": false,
      "last_updated": null
    }
  }
}
```

Champs nouveaux par rapport à l'ancien format :
- `issue_type` : "Epic", "Story", "Bug", "Task", "Sub-task"
- `status_category` : "TO DO", "IN PROGRESS", "DONE" (calculé depuis le statut)
- `priority` : "Highest", "High", "Medium", "Low", "Lowest"
- `epic_key` : clé de l'Epic parente (null si absent ou si Epic lui-même)
- `parent_key` : clé du ticket parent pour les sous-tâches
- `subtask_keys` : liste des clés de sous-tâches
- `linked_issues` : liste de dicts `{"key": "POT-X", "link_type": "is blocked by"}`
- `story_points` : int ou null
- `last_updated` : timestamp ISO du dernier événement simulé

### 1.2 Mettre à jour `StateManager` pour les nouveaux champs

Dans `state_manager.py`, ajouter les méthodes suivantes :

```python
def get_status_category(self, status: str) -> str:
    """Retourne la catégorie d'un statut Jira."""
    todo_statuses = {'IDEA', 'TO DO'}
    done_statuses = {'DONE', 'CANCELLED'}
    status_upper = status.upper()
    if status_upper in todo_statuses:
        return 'TO DO'
    elif status_upper in done_statuses:
        return 'DONE'
    else:
        return 'IN PROGRESS'

def get_tickets_by_type(self, issue_type: str, team_id: str | None = None) -> list[dict]:
    """Retourne les tickets d'un type donné, optionnellement filtrés par équipe."""
    state = self.load()
    result = []
    for ticket in state.get('tickets', {}).values():
        if ticket.get('issue_type', '').lower() == issue_type.lower():
            if team_id is None or ticket.get('team_id') == team_id:
                result.append(ticket)
    return result

def get_epics(self, team_id: str | None = None) -> list[dict]:
    """Retourne les Epics disponibles (non-DONE)."""
    state = self.load()
    epics = []
    for ticket in state.get('tickets', {}).values():
        if (ticket.get('issue_type') == 'Epic'
                and ticket.get('status_category') != 'DONE'):
            if team_id is None or ticket.get('team_id') == team_id:
                epics.append(ticket)
    return epics

def get_members_by_role(self, role: str, team_id: str | None = None) -> list[dict]:
    """Retourne les membres disponibles ayant le rôle spécifié."""
    state = self.load()
    result = []
    for member_id, data in state.get('members', {}).items():
        if data.get('role', '').lower() == role.lower():
            if data.get('availability') == 'available':
                team_ids = data.get('team_ids', [data.get('team_id', '')])
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
    if ticket:
        link = {'key': linked_key, 'link_type': link_type}
        if link not in ticket.get('linked_issues', []):
            ticket.setdefault('linked_issues', []).append(link)
            self.save(state)
```

### 1.3 Mettre à jour `bootstrap_state.py` pour les nouveaux champs

Enrichir `get_tickets_for_project` dans `jira_client.py` pour récupérer
les champs supplémentaires :

```python
# Dans get_tickets_for_project(), mettre à jour les fields demandés
payload = {
    "jql": (f"project = {self.project_key} "
            f"AND statusCategory != Done "
            f"ORDER BY updated DESC"),
    "maxResults": 100,
    "fields": [
        "summary", "status", "assignee", "issuetype",
        "priority", "parent", "subtasks", "issuelinks",
        "story_points", "customfield_10016",  # story points Jira
        "customfield_10014",  # epic link (selon config Jira)
        "customfield_10020"   # sprint (pour usage futur)
    ]
}
```

Dans `bootstrap_state.py`, normaliser chaque ticket avec les nouveaux champs :

```python
def _normalize_ticket(issue: dict, default_team_id: str,
                      status_manager) -> dict:
    """Normalise un issue Jira en dict state enrichi."""
    fields = issue.get('fields', {})
    assignee = fields.get('assignee') or {}
    issue_type = fields.get('issuetype', {}).get('name', 'Story')
    status_name = fields.get('status', {}).get('name', 'TO DO')
    priority = fields.get('priority', {}).get('name', 'Medium')

    # Récupération Epic parent
    epic_key = None
    parent = fields.get('parent')
    parent_key = None
    if parent:
        parent_type = parent.get('fields', {}).get('issuetype', {}).get('name', '')
        if parent_type == 'Epic':
            epic_key = parent.get('key')
        else:
            parent_key = parent.get('key')

    # Sous-tâches
    subtask_keys = [s['key'] for s in fields.get('subtasks', [])]

    # Liens
    linked_issues = []
    for link in fields.get('issuelinks', []):
        if 'outwardIssue' in link:
            linked_issues.append({
                'key': link['outwardIssue']['key'],
                'link_type': link.get('type', {}).get('outward', 'relates to')
            })
        if 'inwardIssue' in link:
            linked_issues.append({
                'key': link['inwardIssue']['key'],
                'link_type': link.get('type', {}).get('inward', 'is blocked by')
            })

    # Story points (essayer plusieurs champs custom)
    story_points = (fields.get('story_points')
                    or fields.get('customfield_10016')
                    or fields.get('customfield_10028'))

    return {
        'key': issue['key'],
        'summary': fields.get('summary', ''),
        'issue_type': issue_type,
        'status': status_name,
        'status_category': status_manager.get_status_category(status_name),
        'priority': priority,
        'assignee_id': assignee.get('accountId', ''),
        'team_id': default_team_id,
        'epic_key': epic_key,
        'parent_key': parent_key,
        'subtask_keys': subtask_keys,
        'linked_issues': linked_issues,
        'story_points': story_points,
        'is_blocked': False,
        'last_updated': None
    }
```

Aussi mettre à jour le format des membres pour supporter `team_ids` (liste) :

```python
# Dans bootstrap_state.py, construire members depuis teams.yaml
members: dict = {}
for team in teams_config.get('teams', []):
    for m in team.get('members', []):
        mid = m['id']
        if mid in members:
            # Membre déjà présent — ajouter l'équipe à team_ids
            if team['id'] not in members[mid]['team_ids']:
                members[mid]['team_ids'].append(team['id'])
        else:
            members[mid] = {
                'availability': m.get('availability', 'available'),
                'current_tickets': [],
                'team_ids': [team['id']],
                'display_name': m.get('display_name', ''),
                'role': m.get('role', 'dev'),
                'jira_account_id': m.get('jira_account_id', '')
            }
```

---

## PARTIE 2 — Mise à jour de `scenario_engine.py`

### 2.1 Nouveau fichier `config/scenarios.yaml` — 7 scénarios phase 5A

Remplacer intégralement `config/scenarios.yaml` :

```yaml
# Phase 5A — 7 scénarios de base avec pondération réaliste
scenarios:

  - id: mise_a_jour_progression
    type: add_comment
    weight: 25
    description: "Commentaire de suivi d'un DEV sur une Story en IN PROGRESS"
    constraints:
      issue_types: ["Story"]
      statuses: ["IN PROGRESS"]
      actor_roles: ["DEV", "lead"]

  - id: engagement
    type: change_status
    weight: 20
    description: "Passage d'un ticket de TO DO à IN PROGRESS"
    constraints:
      issue_types: ["Story", "Bug", "Task"]
      statuses: ["TO DO"]
      target_status: "IN PROGRESS"
      actor_roles: ["DEV", "lead", "BA"]

  - id: demande_review
    type: change_status
    weight: 15
    description: "Passage de IN PROGRESS à IN REVIEW — DEV ou Lead uniquement"
    constraints:
      issue_types: ["Story", "Bug"]
      statuses: ["IN PROGRESS"]
      target_status: "IN REVIEW"
      actor_roles: ["DEV", "lead"]

  - id: finalisation
    type: change_status
    weight: 12
    description: "Passage de IN REVIEW à DONE — QA, BA ou Lead uniquement"
    constraints:
      issue_types: ["Story", "Bug", "Task"]
      statuses: ["IN REVIEW"]
      target_status: "DONE"
      actor_roles: ["QA", "BA", "lead"]
      guard: "no_open_subtasks"

  - id: precision_qa
    type: add_comment
    weight: 10
    description: "Commentaire d'un QA sur un ticket en IN REVIEW"
    constraints:
      issue_types: ["Story", "Bug"]
      statuses: ["IN REVIEW"]
      actor_roles: ["QA", "lead"]

  - id: blocage
    type: change_status
    weight: 8
    description: "Passage au statut BLOCKED avec commentaire IA obligatoire"
    constraints:
      issue_types: ["Story", "Bug"]
      statuses: ["IN PROGRESS", "IN REVIEW"]
      target_status: "BLOCKED"
      actor_roles: ["DEV", "QA", "lead"]
      requires_ai_comment: true

  - id: passage_de_relais
    type: change_assignee
    weight: 10
    description: "Réassignation d'un ticket en cours à un autre membre"
    constraints:
      issue_types: ["Story", "Bug", "Task"]
      statuses: ["IN PROGRESS", "IN REVIEW", "BLOCKED"]
      actor_roles: ["lead", "DEV", "BA"]
```

### 2.2 Refactorer `ScenarioEngine.build_event()`

Réécrire `build_event` pour supporter les contraintes du `scenarios.yaml` enrichi.
La nouvelle logique doit :

1. Lire les `constraints` du scénario
2. Filtrer les tickets selon `issue_types` et `statuses`
3. Filtrer les membres selon `actor_roles` ET leur appartenance à l'équipe du ticket
4. Appliquer les garde-fous (`guard`) :
   - `no_open_subtasks` : vérifier que le ticket n'a pas de sous-tâches en IN PROGRESS

```python
def build_event(self, scenario: dict, state: dict,
                teams_config: dict) -> dict | None:
    """Construit un événement en respectant les contraintes du scénario."""
    from state_manager import StateManager
    sm = StateManager()
    constraints = scenario.get('constraints', {})

    allowed_types    = constraints.get('issue_types', None)
    allowed_statuses = constraints.get('statuses', None)
    actor_roles      = constraints.get('actor_roles', None)
    target_status    = constraints.get('target_status', None)
    guard            = constraints.get('guard', None)

    # 1. Filtrer les tickets candidats
    candidates = []
    for ticket in state.get('tickets', {}).values():
        if allowed_types and ticket.get('issue_type') not in allowed_types:
            continue
        if allowed_statuses and ticket.get('status') not in allowed_statuses:
            continue
        if ticket.get('status_category') == 'DONE':
            continue
        # Garde-fou : pas de sous-tâches ouvertes pour DONE
        if guard == 'no_open_subtasks':
            subtasks = ticket.get('subtask_keys', [])
            open_subs = [
                k for k in subtasks
                if state.get('tickets', {}).get(k, {}).get('status_category') == 'IN PROGRESS'
            ]
            if open_subs:
                continue
        candidates.append(ticket)

    if not candidates:
        logger.info("Aucun ticket candidat pour le scénario '%s'",
                    scenario.get('id'))
        return None

    # 2. Choisir un ticket
    import random
    ticket = random.choice(candidates)
    team_id = ticket.get('team_id', '')

    # 3. Filtrer les membres selon rôle et appartenance à l'équipe du ticket
    available_members = []
    for member_id, data in state.get('members', {}).items():
        if data.get('availability') != 'available':
            continue
        member_teams = data.get('team_ids', [data.get('team_id', '')])
        if team_id and team_id not in member_teams:
            continue
        if actor_roles:
            member_role = data.get('role', '').lower()
            allowed_lower = [r.lower() for r in actor_roles]
            if member_role not in allowed_lower:
                continue
        available_members.append({'id': member_id, **data})

    if not available_members:
        logger.info("Aucun membre disponible avec le bon rôle pour '%s'",
                    scenario.get('id'))
        return None

    member = random.choice(available_members)

    return {
        'type': scenario.get('type'),
        'scenario_id': scenario.get('id'),
        'team_id': team_id,
        'member_id': member['id'],
        'member_name': member.get('display_name', member['id']),
        'member_role': member.get('role', 'dev'),
        'ticket_key': ticket['key'],
        'ticket_summary': ticket.get('summary', ''),
        'issue_type': ticket.get('issue_type', 'Story'),
        'context': {
            'current_status': ticket.get('status'),
            'status_category': ticket.get('status_category'),
            'target_status': target_status,
            'is_blocked': ticket.get('is_blocked', False),
            'priority': ticket.get('priority', 'Medium'),
            'epic_key': ticket.get('epic_key'),
            'requires_ai_comment': constraints.get('requires_ai_comment', False),
        },
        'ai_content': None
    }
```

---

## PARTIE 3 — Mise à jour de `scheduler.py`

### 3.1 Gérer les nouveaux types d'événements et la propagation Epic

Mettre à jour la boucle d'exécution dans `run_simulation` pour gérer
les nouveaux champs et la propagation Epic (probabiliste) :

```python
import random as _random

# Dans la boucle, après l'exécution de change_status vers IN PROGRESS :
elif stype == 'change_status':
    current = event['context']['current_status']
    target  = event['context'].get('target_status')

    if not target:
        # Fallback : avancer dans le workflow si pas de target défini
        status_flow = ['TO DO', 'IN PROGRESS', 'IN REVIEW', 'DONE']
        idx = status_flow.index(current) + 1 if current in status_flow else 0
        target = status_flow[min(idx, len(status_flow) - 1)]

    jira_client.transition_ticket(key, target)
    state_manager.update_ticket_status(key, target)
    state_manager.update_ticket_field(key, 'status_category',
                                      state_manager.get_status_category(target))

    # Propagation Epic (70% de chance si Story passe en IN PROGRESS)
    if target == 'IN PROGRESS' and event.get('issue_type') == 'Story':
        epic_key = event['context'].get('epic_key')
        if epic_key and _random.random() < 0.70:
            reloaded = state_manager.load()
            epic = reloaded.get('tickets', {}).get(epic_key, {})
            if epic.get('status_category') == 'TO DO':
                jira_client.transition_ticket(epic_key, 'IN PROGRESS')
                state_manager.update_ticket_status(epic_key, 'IN PROGRESS')
                state_manager.update_ticket_field(epic_key, 'status_category',
                                                  'IN PROGRESS')
                logger.info("Epic %s propagée en IN PROGRESS (70%% rule)", epic_key)

    # Commentaire obligatoire si blocage
    if target == 'BLOCKED':
        comment = event.get('ai_content') or "Ticket bloqué — en attente de résolution."
        jira_client.add_comment(key, comment)
```

---

## PARTIE 4 — Mise à jour de `jira_client.py`

### 4.1 Ajouter les méthodes manquantes pour les nouveaux scénarios

Ajouter dans `JiraClient` :

#### `update_issue_field(ticket_key, field_name, value)`
```python
def update_issue_field(self, ticket_key: str,
                       field_name: str, value) -> dict:
    """Met à jour un champ d'un ticket (priority, story_points, description…)."""
    if self.dry_run:
        return self._dry_log('update_field', ticket_key,
                             f'{field_name} = {value}')
    url = f"{self.base_url}/rest/api/3/issue/{ticket_key}"
    r = requests.put(
        url,
        headers=self._get_auth_headers(),
        json={"fields": {field_name: value}},
        timeout=15
    )
    return self._handle_response(r, f"update_issue_field({ticket_key}.{field_name})")
```

#### `create_issue_link(from_key, to_key, link_type)`
```python
def create_issue_link(self, from_key: str,
                      to_key: str, link_type: str) -> dict:
    """Crée un lien entre deux tickets."""
    if self.dry_run:
        return self._dry_log('create_link', from_key,
                             f'{link_type} → {to_key}')
    url = f"{self.base_url}/rest/api/3/issueLink"
    r = requests.post(
        url,
        headers=self._get_auth_headers(),
        json={
            "type": {"name": link_type},
            "inwardIssue": {"key": from_key},
            "outwardIssue": {"key": to_key}
        },
        timeout=15
    )
    return self._handle_response(r, f"create_issue_link({from_key}→{to_key})")
```

#### `create_issue(fields_dict)` — pour créer des tickets (Bugs, Stories, sous-tâches)
```python
def create_issue(self, fields: dict) -> dict:
    """Crée un nouveau ticket Jira."""
    if self.dry_run:
        summary = fields.get('summary', 'Nouveau ticket')
        issue_type = fields.get('issuetype', {}).get('name', 'Story')
        return self._dry_log('create_issue', self.project_key,
                             f'{issue_type}: "{summary[:60]}"')
    url = f"{self.base_url}/rest/api/3/issue"
    r = requests.post(
        url,
        headers=self._get_auth_headers(),
        json={"fields": fields},
        timeout=15
    )
    return self._handle_response(r, "create_issue")
```

---

## PARTIE 5 — Tests à ajouter

### `tests/test_scenario_engine_v2.py`

```python
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
        'POT-1': {'key': 'POT-1', 'summary': 'Auth epic',
                  'issue_type': 'Epic', 'status': 'IN PROGRESS',
                  'status_category': 'IN PROGRESS', 'priority': 'High',
                  'assignee_id': 'lionel_d', 'team_id': 'phoenix',
                  'epic_key': None, 'subtask_keys': [], 'linked_issues': [],
                  'is_blocked': False},
        'POT-2': {'key': 'POT-2', 'summary': 'Implement OAuth',
                  'issue_type': 'Story', 'status': 'IN PROGRESS',
                  'status_category': 'IN PROGRESS', 'priority': 'High',
                  'assignee_id': 'paul', 'team_id': 'phoenix',
                  'epic_key': 'POT-1', 'subtask_keys': [], 'linked_issues': [],
                  'is_blocked': False},
        'POT-3': {'key': 'POT-3', 'summary': 'Login bug',
                  'issue_type': 'Bug', 'status': 'IN REVIEW',
                  'status_category': 'IN PROGRESS', 'priority': 'High',
                  'assignee_id': 'gala', 'team_id': 'phoenix',
                  'epic_key': None, 'subtask_keys': [], 'linked_issues': [],
                  'is_blocked': False},
    }
}


def test_demande_review_only_dev_or_lead():
    """Seuls DEV et Lead peuvent demander une review."""
    engine = ScenarioEngine()
    scenario = next(s for s in engine.scenarios if s['id'] == 'demande_review')
    # Retirer paul (DEV) et lionel (lead) — ne garder que gala (QA)
    state = {**BASE_STATE, 'members': {
        'gala': BASE_STATE['members']['gala']
    }}
    event = engine.build_event(scenario, state, TEAMS_CFG)
    assert event is None  # QA ne peut pas demander une review


def test_finalisation_only_qa_ba_lead():
    """Seuls QA, BA et Lead peuvent passer en DONE."""
    engine = ScenarioEngine()
    scenario = next(s for s in engine.scenarios if s['id'] == 'finalisation')
    # Ticket en IN REVIEW requis
    state = {**BASE_STATE}
    state['tickets']['POT-3']['status'] = 'IN REVIEW'
    # Ne garder que paul (DEV) — ne doit pas pouvoir valider
    state = {**state, 'members': {'paul': BASE_STATE['members']['paul']}}
    event = engine.build_event(scenario, state, TEAMS_CFG)
    assert event is None


def test_event_contains_issue_type():
    """L'event doit contenir issue_type pour les providers IA."""
    engine = ScenarioEngine()
    scenario = next(s for s in engine.scenarios
                    if s['id'] == 'mise_a_jour_progression')
    event = engine.build_event(scenario, BASE_STATE, TEAMS_CFG)
    assert event is not None
    assert 'issue_type' in event
    assert event['issue_type'] in ['Story', 'Bug', 'Task', 'Epic', 'Sub-task']


def test_blocage_requires_ai_comment_flag():
    """L'event blocage doit porter le flag requires_ai_comment."""
    engine = ScenarioEngine()
    scenario = next(s for s in engine.scenarios if s['id'] == 'blocage')
    event = engine.build_event(scenario, BASE_STATE, TEAMS_CFG)
    if event:  # peut être None si pas de ticket éligible
        assert event['context'].get('requires_ai_comment') is True
```

---

## Ordre d'exécution pour Copilot

1. Mettre à jour `state_manager.py` (Partie 1.2) — nouvelles méthodes
2. Mettre à jour `jira_client.py` — `get_tickets_for_project` + nouvelles méthodes (Parties 1.3 + 4.1)
3. Mettre à jour `bootstrap_state.py` — format enrichi + dédup membres (Partie 1.3)
4. Remplacer `config/scenarios.yaml` (Partie 2.1)
5. Refactorer `scenario_engine.py` — `build_event` (Partie 2.2)
6. Mettre à jour `scheduler.py` — nouveaux types + propagation Epic (Partie 3.1)
7. Ajouter `tests/test_scenario_engine_v2.py` (Partie 5)
8. Lancer `python -m pytest -v` → tous les tests doivent passer
9. Lancer `python bootstrap_state.py --project POT`
10. Vérifier `state.json` — tickets avec `issue_type`, `epic_key`, `status_category`
11. Lancer `python main.py --events 5 --dry-run`
12. Vérifier les logs — scénarios respectent les rôles et les statuts

---

## Règles de code

- Python 3.11+, type hints, docstrings en français
- `logging` uniquement — pas de `print` sauf dans `_dry_log`
- `load_dotenv()` en première instruction de tout point d'entrée
- Chemins avec `pathlib.Path`
- Ne pas casser les tests existants (11 tests doivent toujours passer)
- `DRY_RUN` reste à la valeur du `.env` — ne pas modifier
