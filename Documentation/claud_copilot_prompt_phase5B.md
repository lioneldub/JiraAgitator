# Prompt GitHub Copilot — Phase 5B : Corrections state + 14 nouveaux scénarios
# Jira Activity Simulator — Règles métier complètes

---

## Contexte et état actuel

Analyse du `state.json` actuel révèle 4 problèmes à corriger AVANT d'ajouter
les nouveaux scénarios. Ces corrections sont fondamentales — les règles métier
de la 5B s'appuient sur des données correctes dans le state.

Fichiers principaux concernés :
- `bootstrap_state.py` — ingestion et normalisation
- `state_manager.py` — nouvelles méthodes
- `scheduler.py` — mise à jour exhaustive après chaque événement
- `config/scenarios.yaml` — 14 nouveaux scénarios

---

## PARTIE 1 — Corrections bloquantes du state

### 1.1 Résolution bidirectionnelle accountId ↔ member_id au bootstrap

**Problème** : `assignee_id` dans les tickets stocke l'accountId Jira brut
(ex: `"712020:b977ae3a..."`) alors que les clés du dict `members` sont les
member_id (`"paul"`, `"gala"`…). Le ScenarioEngine ne peut pas identifier
l'assignee courant, ni exclure le bon membre d'une réassignation.

**Correction** dans `bootstrap_state.py` : construire un reverse-map
`accountId → member_id` depuis `teams.yaml` et l'appliquer à chaque ticket :

```python
# Construire le reverse-map après la construction de members
account_to_member: dict[str, str] = {}
for mid, data in members.items():
    aid = data.get('jira_account_id', '')
    if aid:
        account_to_member[aid] = mid

# Lors de la normalisation de chaque ticket, résoudre l'assignee
for t in tickets_raw:
    raw_assignee = t.get('assignee_id', '')
    t['assignee_id'] = account_to_member.get(raw_assignee, raw_assignee)
    # Si non résolu, logger un warning avec la clé et l'accountId
    if t['assignee_id'] == raw_assignee and raw_assignee:
        logger.warning(
            "Ticket %s : assignee accountId '%s' non résolu "
            "— vérifier jira_account_id dans teams.yaml",
            t['key'], raw_assignee[:20]
        )
    t['team_id'] = team_id
    all_tickets[t['key']] = t
```

Même logique dans `jira_client.get_tickets_for_project()` — appliquer
la résolution avant de retourner la liste, en passant le `account_to_member`
en paramètre optionnel ou en le reconstruisant depuis `teams.yaml`.

### 1.2 Synchroniser `is_blocked` avec le statut BLOCKED au bootstrap

**Problème** : tous les tickets ont `is_blocked: false` même quand
`status == "BLOCKED"`. Les guards de la phase 5B vérifient `is_blocked`.

**Correction** dans `_normalize_ticket` (ou dans la boucle de bootstrap) :

```python
# Après avoir déterminé status_name
is_blocked = status_name.upper() == 'BLOCKED'

# Dans le dict ticket retourné :
'is_blocked': is_blocked,
```

### 1.3 Mise à jour exhaustive du state après CHAQUE événement dans `scheduler.py`

**Problème** : seuls certains champs sont mis à jour après exécution
(status via `update_ticket_status`), mais `status_category`, `is_blocked`,
`assignee_id`, et `last_updated` ne sont pas systématiquement synchronisés.

**Correction** : créer une méthode `sync_ticket_after_event` dans `StateManager`
qui met à jour tous les champs en une seule opération atomique :

```python
def sync_ticket_after_event(self, ticket_key: str,
                             updates: dict) -> None:
    """
    Met à jour atomiquement tous les champs d'un ticket après un événement.
    updates : dict des champs à modifier (status, assignee_id, is_blocked…)
    Recalcule automatiquement status_category et last_updated.
    """
    import datetime
    state = self.load()
    ticket = state.get('tickets', {}).get(ticket_key)
    if not ticket:
        logger.warning('sync_ticket_after_event : ticket %s introuvable',
                       ticket_key)
        return
    for field, value in updates.items():
        ticket[field] = value
    # Recalcul automatique de status_category si status a changé
    if 'status' in updates:
        ticket['status_category'] = self.get_status_category(
            updates['status']
        )
    # Synchronisation is_blocked avec le statut
    if 'status' in updates:
        ticket['is_blocked'] = updates['status'].upper() == 'BLOCKED'
    # Timestamp systématique
    ticket['last_updated'] = datetime.datetime.utcnow().isoformat()
    self.save(state)
```

**Dans `scheduler.py`**, remplacer tous les appels éparpillés à
`update_ticket_status`, `update_ticket_field`, `update_ticket_assignee`
par un seul appel à `sync_ticket_after_event` :

```python
# Exemple pour change_status :
state_manager.sync_ticket_after_event(key, {
    'status': target
})

# Exemple pour change_assignee :
state_manager.sync_ticket_after_event(key, {
    'assignee_id': new_assignee
})

# Exemple pour blocage :
state_manager.sync_ticket_after_event(key, {
    'status': 'BLOCKED',
    'is_blocked': True
})
```

### 1.4 Guard "bloquant absent du state" pour les liens `is blocked by`

**Problème** : KAN-9 a un lien `is blocked by KAN-7` mais KAN-7 est absent
du state (DONE dans Jira → exclu du bootstrap). Une KeyError est possible.

**Correction** dans `scenario_engine.py`, dans le guard de finalisation
(et dans le futur guard de déblocage) :

```python
def _is_blocking_resolved(self, ticket: dict, state: dict) -> bool:
    """
    Retourne True si tous les tickets bloquants sont résolus.
    Un ticket bloquant absent du state est considéré comme résolu
    (probablement DONE dans Jira).
    """
    for link in ticket.get('linked_issues', []):
        if link.get('link_type', '').lower() in ('is blocked by',
                                                   'est bloqué par'):
            blocking_key = link['key']
            blocking_ticket = state.get('tickets', {}).get(blocking_key)
            if blocking_ticket is None:
                # Absent du state = considéré résolu
                logger.debug(
                    "Ticket bloquant %s absent du state — "
                    "considéré résolu", blocking_key
                )
                continue
            if blocking_ticket.get('status_category') != 'DONE':
                return False
    return True
```

---

## PARTIE 2 — 14 nouveaux scénarios dans `config/scenarios.yaml`

Ajouter les scénarios suivants à la suite des 8 existants
(ne pas supprimer les scénarios de la phase 5A) :

```yaml
  # --- Scénarios Phase 5B ---

  - id: deblocage
    type: change_status
    weight: 9
    description: "Passage de BLOCKED vers IN PROGRESS — déblocage d'un ticket"
    constraints:
      issue_types: ["Story", "Bug", "Feature", "Task"]
      statuses: ["BLOCKED"]
      target_status: "IN PROGRESS"
      actor_roles: ["DEV", "lead", "BA"]

  - id: rejet_review
    type: change_status
    weight: 7
    description: "Retour d'un ticket de IN REVIEW vers IN PROGRESS après retour QA"
    constraints:
      issue_types: ["Story", "Bug", "Feature"]
      statuses: ["IN REVIEW"]
      target_status: "IN PROGRESS"
      actor_roles: ["QA", "lead"]

  - id: incident_run
    type: create_issue
    weight: 5
    description: "Création d'un Bug Medium directement en TO DO (incident production)"
    constraints:
      actor_roles: ["QA", "lead", "DEV"]
      issue_type_to_create: "Bug"
      priority_to_create: "Medium"
      initial_status: "TO DO"

  - id: urgence_production
    type: create_issue
    weight: 3
    description: "Création d'un Bug Highest passant immédiatement en IN PROGRESS"
    constraints:
      actor_roles: ["lead", "QA"]
      issue_type_to_create: "Bug"
      priority_to_create: "Highest"
      initial_status: "IN PROGRESS"

  - id: affinement_backlog
    type: add_comment
    weight: 8
    description: "Commentaire d'affinement sur une Epic ou Story en TO DO / IDEA"
    constraints:
      issue_types: ["Epic", "Story", "Feature"]
      statuses: ["TO DO", "IDEA"]
      actor_roles: ["lead", "BA"]

  - id: decomposition
    type: create_subtask
    weight: 5
    description: "Création d'une sous-tâche sur une Story existante en IN PROGRESS"
    constraints:
      issue_types: ["Story", "Feature"]
      statuses: ["IN PROGRESS"]
      actor_roles: ["DEV", "lead"]

  - id: lien_dependance
    type: create_link
    weight: 4
    description: "Création d'un lien 'is blocked by' entre deux tickets"
    constraints:
      issue_types: ["Story", "Bug", "Feature"]
      statuses: ["IN PROGRESS", "TO DO"]
      actor_roles: ["lead", "DEV"]
      link_type: "is blocked by"

  - id: repriorisation
    type: update_field
    weight: 5
    description: "Changement de priorité d'un ticket en TO DO"
    constraints:
      issue_types: ["Story", "Bug", "Feature", "Epic"]
      statuses: ["TO DO", "IDEA"]
      actor_roles: ["lead", "BA"]
      field_to_update: "priority"

  - id: alimentation_produit
    type: create_issue
    weight: 4
    description: "Création d'une nouvelle User Story rattachée à une Epic existante"
    constraints:
      actor_roles: ["BA", "lead"]
      issue_type_to_create: "Story"
      priority_to_create: "Medium"
      initial_status: "TO DO"
      requires_epic: true

  - id: bug_de_dev
    type: create_issue
    weight: 4
    description: "Création d'un Bug lié à une Story pendant le cycle de dev"
    constraints:
      actor_roles: ["DEV", "QA"]
      issue_type_to_create: "Bug"
      priority_to_create: "Medium"
      initial_status: "TO DO"
      link_to_parent: true

  - id: auto_assignation
    type: change_assignee
    weight: 6
    description: "Un membre s'assigne lui-même un ticket en TO DO"
    constraints:
      issue_types: ["Story", "Bug", "Task", "Feature"]
      statuses: ["TO DO", "IDEA"]
      actor_roles: ["DEV", "BA", "lead"]
      assign_to_self: true

  - id: nettoyage
    type: change_status
    weight: 3
    description: "Passage d'un vieux ticket en CANCELLED — tout statut sauf DONE"
    constraints:
      issue_types: ["Story", "Bug", "Task", "Feature"]
      statuses: ["TO DO", "IDEA", "IN PROGRESS", "BLOCKED"]
      target_status: "CANCELLED"
      actor_roles: ["lead", "BA"]

  - id: re_estimation
    type: update_field
    weight: 4
    description: "Modification des Story Points d'un ticket en cours"
    constraints:
      issue_types: ["Story", "Feature", "Bug"]
      statuses: ["TO DO", "IN PROGRESS", "BLOCKED"]
      actor_roles: ["DEV", "lead", "BA"]
      field_to_update: "story_points"

  - id: relance_lead
    type: add_comment
    weight: 6
    description: "Commentaire du Lead sur un ticket stagnant (last_updated > 3 jours)"
    constraints:
      issue_types: ["Story", "Bug", "Feature", "Epic"]
      statuses: ["IN PROGRESS", "BLOCKED"]
      actor_roles: ["lead"]
      guard: "stagnant_ticket"
```

---

## PARTIE 3 — Nouveaux types d'événements dans `scheduler.py`

La boucle d'exécution doit gérer les nouveaux types introduits en phase 5B.
Ajouter les branches suivantes dans le bloc `try` de `run_simulation` :

### 3.1 `create_issue` — création de ticket

```python
elif stype == 'create_issue':
    constraints = event.get('context', {})
    issue_type  = constraints.get('issue_type_to_create', 'Bug')
    priority    = constraints.get('priority_to_create', 'Medium')
    initial_st  = constraints.get('initial_status', 'TO DO')
    requires_epic = constraints.get('requires_epic', False)
    link_to_parent = constraints.get('link_to_parent', False)

    # Trouver une Epic cible si nécessaire
    epic_key = None
    if requires_epic or link_to_parent:
        epics = [t for t in state.get('tickets', {}).values()
                 if t.get('issue_type') == 'Epic'
                 and t.get('status_category') != 'DONE'
                 and t.get('team_id') == event.get('team_id')]
        if epics:
            import random
            epic_key = random.choice(epics)['key']

    # Construire le summary via l'IA
    summary = event.get('ai_content') or f"[{issue_type}] Nouveau ticket"

    fields = {
        'project': {'key': event.get('ticket_key', 'POT').split('-')[0]},
        'summary': summary,
        'issuetype': {'name': issue_type},
        'priority': {'name': priority},
        'assignee': {'accountId': _resolve_account_id(
            event['member_id'], state_manager
        )},
    }
    if epic_key:
        # Utiliser parent pour lier à l'Epic (Jira Next-gen)
        fields['parent'] = {'key': epic_key}

    result = jira_client.create_issue(fields)

    # Si l'issue est créée et doit démarrer en IN PROGRESS
    if initial_st == 'IN PROGRESS' and result.get('key'):
        new_key = result['key']
        jira_client.transition_ticket(new_key, 'IN PROGRESS')

    # Si lien vers une Story parente (bug_de_dev)
    if link_to_parent and event.get('ticket_key'):
        jira_client.create_issue_link(
            result.get('key', ''),
            event['ticket_key'],
            'relates to'
        )
```

### 3.2 `create_subtask` — décomposition

```python
elif stype == 'create_subtask':
    parent_key = event['ticket_key']
    summary    = event.get('ai_content') or "Sous-tâche technique"
    account_id = _resolve_account_id(event['member_id'], state_manager)

    result = jira_client.create_subtask(parent_key, summary, account_id)

    # Mettre à jour subtask_keys du parent dans le state
    if result.get('key'):
        state_manager.add_subtask_to_parent(parent_key, result['key'])
```

### 3.3 `create_link` — lien de dépendance

```python
elif stype == 'create_link':
    from_key  = event['ticket_key']
    link_type = event['context'].get('link_type', 'relates to')

    # Choisir un ticket cible différent du ticket source
    candidates = [
        t['key'] for t in state.get('tickets', {}).values()
        if t['key'] != from_key
        and t.get('status_category') != 'DONE'
        and t.get('team_id') == event.get('team_id')
    ]
    if candidates:
        import random
        to_key = random.choice(candidates)
        jira_client.create_issue_link(from_key, to_key, link_type)
        state_manager.add_issue_link(from_key, to_key, link_type)
        # Si lien "is blocked by", mettre à jour is_blocked du ticket source
        if 'blocked' in link_type.lower():
            state_manager.sync_ticket_after_event(from_key, {
                'status': 'BLOCKED',
                'is_blocked': True
            })
            jira_client.transition_ticket(from_key, 'BLOCKED')
```

### 3.4 `update_field` — repriorisation / ré-estimation

```python
elif stype == 'update_field':
    field_name = event['context'].get('field_to_update', 'priority')

    if field_name == 'priority':
        priorities = ['Lowest', 'Low', 'Medium', 'High', 'Highest']
        current_p  = event['context'].get('priority', 'Medium')
        current_i  = priorities.index(current_p) if current_p in priorities else 2
        # Changer d'au moins un cran (vers le haut ou le bas)
        import random
        options = [p for p in priorities if p != current_p]
        new_priority = random.choice(options)
        jira_client.update_issue_field(
            key, 'priority', {'name': new_priority}
        )
        state_manager.sync_ticket_after_event(key, {'priority': new_priority})

    elif field_name == 'story_points':
        import random
        sp_options = [1, 2, 3, 5, 8, 13]
        new_sp = random.choice(sp_options)
        # story_points = customfield_10016 sur la plupart des instances Jira
        jira_client.update_issue_field(key, 'customfield_10016', new_sp)
        state_manager.sync_ticket_after_event(key, {'story_points': new_sp})
```

### 3.5 `auto_assignation` — le membre s'assigne lui-même

La branche `change_assignee` existante doit gérer le cas `assign_to_self` :

```python
elif stype == 'change_assignee':
    assign_to_self = event['context'].get('assign_to_self', False)

    if assign_to_self:
        new_assignee = event['member_id']
    else:
        current = event['context'].get('current_assignee_id', '')
        candidates = [
            mid for mid, data in state.get('members', {}).items()
            if data.get('availability') == 'available'
            and mid != current
            and event.get('team_id') in data.get('team_ids', [])
        ]
        if not candidates:
            logger.info("[SKIP] change_assignee — aucun candidat disponible")
            skipped += 1
            continue
        import random
        new_assignee = random.choice(candidates)

    account_id = _resolve_account_id(new_assignee, state_manager)
    jira_client.assign_ticket(key, account_id)
    state_manager.sync_ticket_after_event(key, {'assignee_id': new_assignee})
```

### 3.6 Fonction helper `_resolve_account_id` à ajouter dans `scheduler.py`

```python
def _resolve_account_id(member_id: str,
                        state_manager: 'StateManager') -> str:
    """Résout le jira_account_id depuis un member_id via le state."""
    state = state_manager.load()
    member = state.get('members', {}).get(member_id, {})
    return member.get('jira_account_id', member_id)
```

---

## PARTIE 4 — Nouveaux guards dans `scenario_engine.py`

### 4.1 Guard `stagnant_ticket`

```python
# Dans build_event, ajouter dans le bloc de filtrage des candidats :
if guard == 'stagnant_ticket':
    import datetime
    last_upd = ticket.get('last_updated')
    if not last_upd:
        # Jamais mis à jour = considéré stagnant
        pass
    else:
        try:
            dt = datetime.datetime.fromisoformat(last_upd)
            age = (datetime.datetime.utcnow() - dt).days
            if age < 3:
                continue   # Pas assez stagnant
        except ValueError:
            pass
```

### 4.2 Guard `blocked_by` dans `finalisation`

Dans `build_event`, renforcer le guard `no_open_subtasks` pour inclure
la vérification des liens bloquants :

```python
if guard == 'no_open_subtasks':
    # Vérification sous-tâches ouvertes
    subtasks = ticket.get('subtask_keys', [])
    open_subs = [
        k for k in subtasks
        if state.get('tickets', {}).get(k, {}).get('status_category')
        == 'IN PROGRESS'
    ]
    if open_subs:
        continue
    # Vérification liens bloquants (bloquant absent = considéré résolu)
    if not self._is_blocking_resolved(ticket, state):
        continue
```

### 4.3 Enrichir le dict event avec `current_assignee_id` et les contraintes de création

Dans `build_event`, ajouter `current_assignee_id` dans le context
et propager les contraintes de création dans le context :

```python
return {
    ...
    'context': {
        'current_status': ticket.get('status') if ticket else None,
        'status_category': ticket.get('status_category') if ticket else None,
        'target_status': target_status,
        'is_blocked': ticket.get('is_blocked', False) if ticket else False,
        'priority': ticket.get('priority', 'Medium') if ticket else 'Medium',
        'epic_key': ticket.get('epic_key') if ticket else None,
        'current_assignee_id': ticket.get('assignee_id', '') if ticket else '',
        'requires_ai_comment': constraints.get('requires_ai_comment', False),
        # Contraintes de création propagées pour les scénarios create_issue
        'issue_type_to_create': constraints.get('issue_type_to_create'),
        'priority_to_create': constraints.get('priority_to_create'),
        'initial_status': constraints.get('initial_status'),
        'requires_epic': constraints.get('requires_epic', False),
        'link_to_parent': constraints.get('link_to_parent', False),
        'link_type': constraints.get('link_type'),
        'field_to_update': constraints.get('field_to_update'),
        'assign_to_self': constraints.get('assign_to_self', False),
    },
    ...
}
```

Pour les scénarios `create_issue`, `create_subtask`, `create_link`
qui n'ont pas forcément de ticket source, `build_event` doit retourner
un event sans `ticket_key` obligatoire — adapter la logique pour
que ces scénarios choisissent un membre et optionnellement un ticket.

---

## PARTIE 5 — Tests à ajouter

### `tests/test_state_sync.py`

```python
import json
import pytest
from pathlib import Path
from state_manager import StateManager


def test_sync_ticket_updates_status_category(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sm = StateManager(str(tmp_path / 'state.json'))
    sm.save({
        'last_run': None, 'members': {},
        'tickets': {
            'POT-1': {
                'key': 'POT-1', 'status': 'IN PROGRESS',
                'status_category': 'IN PROGRESS', 'is_blocked': False,
                'last_updated': None
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
    monkeypatch.chdir(tmp_path)
    sm = StateManager(str(tmp_path / 'state.json'))
    sm.save({'last_run': None, 'members': {}, 'tickets': {
        'POT-2': {'key': 'POT-2', 'status': 'IN PROGRESS',
                  'status_category': 'IN PROGRESS',
                  'is_blocked': False, 'last_updated': None}
    }})
    sm.sync_ticket_after_event('POT-2', {'status': 'IN PROGRESS'})
    assert sm.load()['tickets']['POT-2']['is_blocked'] is False


def test_blocking_resolved_when_blocker_absent(tmp_path, monkeypatch):
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
    monkeypatch.chdir(tmp_path)
    from scenario_engine import ScenarioEngine
    engine = ScenarioEngine()
    ticket = {
        'key': 'POT-6',
        'linked_issues': [{'key': 'POT-10', 'link_type': 'is blocked by'}]
    }
    state = {'tickets': {
        'POT-10': {'key': 'POT-10', 'status_category': 'IN PROGRESS'}
    }}
    assert engine._is_blocking_resolved(ticket, state) is False
```

---

## Ordre d'exécution pour Copilot

1. **Correction 1.1** : résolution accountId → member_id dans `bootstrap_state.py`
   et `jira_client.get_tickets_for_project()`
2. **Correction 1.2** : synchronisation `is_blocked` au bootstrap dans `_normalize_ticket`
3. **Correction 1.3** : méthode `sync_ticket_after_event` dans `state_manager.py`
   + remplacement des appels éparpillés dans `scheduler.py`
4. **Correction 1.4** : méthode `_is_blocking_resolved` dans `scenario_engine.py`
5. **Partie 2** : ajouter les 14 scénarios dans `config/scenarios.yaml`
6. **Partie 3** : branches `create_issue`, `create_subtask`, `create_link`,
   `update_field`, `auto_assignation`, helper `_resolve_account_id` dans `scheduler.py`
7. **Partie 4** : guards `stagnant_ticket`, `blocked_by` + enrichissement du dict event
8. **Partie 5** : `tests/test_state_sync.py`
9. `python -m pytest -v` → tous les tests doivent passer
10. `python bootstrap_state.py --projects POT,KAN`
    → vérifier dans les logs que les assignees sont résolus (member_id, pas accountId)
    → vérifier que `is_blocked: true` sur les tickets BLOCKED
11. `python main.py --events 10 --dry-run`
    → vérifier dans les logs que des scénarios variés sont sélectionnés
    → vérifier que chaque événement affiche la clé Jira, le type, le statut et le membre

---

## Sortie console attendue après phase 5B

```
[INFO] AUTO_BOOTSTRAP=true — rafraîchissement du state...
[INFO] Bootstrap — récupération des tickets pour POT...
[INFO]   → 16 ticket(s) récupéré(s) pour POT (équipe: phoenix)
[INFO] Bootstrap — récupération des tickets pour KAN...
[INFO]   → 13 ticket(s) récupéré(s) pour KAN (équipe: phoenix)
[INFO] Bootstrap terminé — 29 ticket(s), 5 membre(s)
[INFO]   Epic : 8 | Story : 10 | Bug : 4 | Task : 3 | Feature : 2 | Blockedx : 5 résolus
[INFO] Run started — 10 events requested
[INFO] Scénario 'deblocage' → ticket POT-8 [Story] statut 'BLOCKED' assigné à Pierre (DEV)
[INFO] [OK] POT-8 | Story (Audit trail des connexions) | BLOCKED → IN PROGRESS | par Pierre
[INFO] Scénario 'incident_run' → membre Gala (QA) | pas de ticket source
[INFO] [OK] Nouveau Bug créé | par Gala
[INFO] Scénario 'relance_lead' → ticket KAN-3 [Epic] statut 'IN PROGRESS' assigné à Lionel (lead)
[INFO] [OK] KAN-3 | Epic (Horror) | IN PROGRESS → — | par Lionel Dubois
[INFO] Run complete — 10 events executed, 0 skipped
[INFO] State saved to state.json
```

---

## Règles

- Python 3.11+, type hints, docstrings en français
- `sync_ticket_after_event` est la SEULE méthode à appeler pour mettre à jour
  un ticket après un événement — supprimer les anciens appels éparpillés
- Tous les statuts dans state.json restent en UPPERCASE
- Les assignee_id dans state.json sont des member_id ("paul", "gala"…),
  jamais des accountId Jira bruts
- `load_dotenv()` en première instruction de tout point d'entrée
- Ne pas modifier `main.py`
- Conserver tous les tests existants (11+ doivent toujours passer)
