# Prompt GitHub Copilot — Hotfix Phase 5A : Bootstrap dynamique + normalisation statuts
# Correction de 3 problèmes bloquants identifiés après les premiers tests

---

## Problèmes identifiés

1. **Aucun scénario retenu** : les `issue_types` dans `scenarios.yaml` ne couvrent
   pas les Epics et Features — si Jira renvoie principalement ces types, 0 ticket éligible.

2. **Comparaison de statuts silencieusement cassée** : Jira retourne des statuts
   en casse mixte (`"In Progress"`, `"To Do"`) alors que les contraintes YAML cherchent
   `"IN PROGRESS"`, `"TO DO"` en majuscules — la comparaison échoue sans erreur visible.

3. **State.json périmé** : Jira évolue entre deux runs, le state devient incohérent.
   Il faut un bootstrap automatique avant chaque simulation, configurable par projet.

---

## CORRECTION 1 — Normalisation des statuts partout dans le code

### 1.1 Dans `state_manager.py` — normaliser à la lecture

Modifier `get_status_category` pour être insensible à la casse ET gérer
les variantes de nommage Jira :

```python
def get_status_category(self, status: str) -> str:
    """Retourne la catégorie normalisée d'un statut Jira (insensible à la casse)."""
    s = status.strip().upper()
    todo_statuses     = {'IDEA', 'TO DO', 'TODO', 'OPEN', 'BACKLOG'}
    done_statuses     = {'DONE', 'CLOSED', 'CANCELLED', 'CANCELED',
                         'RESOLVED', 'COMPLETE', 'COMPLETED'}
    if s in todo_statuses:
        return 'TO DO'
    elif s in done_statuses:
        return 'DONE'
    else:
        return 'IN PROGRESS'
```

### 1.2 Dans `bootstrap_state.py` — normaliser les statuts à l'ingestion

Dans la fonction `_normalize_ticket`, normaliser le statut reçu de Jira
en UPPERCASE immédiatement pour que le state.json soit toujours cohérent :

```python
# Normalisation du statut dès la récupération Jira
raw_status = fields.get('status', {}).get('name', 'TO DO')
status_name = raw_status.strip().upper()   # ← normaliser ici
```

### 1.3 Dans `scenario_engine.py` — comparaison insensible à la casse

Dans `build_event`, lors du filtrage des tickets par statut, normaliser
avant de comparer :

```python
# Lors du filtrage des tickets candidats
ticket_status = ticket.get('status', '').strip().upper()
if allowed_statuses:
    allowed_upper = [s.strip().upper() for s in allowed_statuses]
    if ticket_status not in allowed_upper:
        continue

# Pareil pour status_category
ticket_cat = ticket.get('status_category', '').strip().upper()
if ticket_cat == 'DONE':
    continue
```

---

## CORRECTION 2 — Ajouter Epics et Features dans `scenarios.yaml`

Remplacer intégralement `config/scenarios.yaml` par la version enrichie
qui couvre tous les types de tickets du projet POT :

```yaml
scenarios:

  - id: mise_a_jour_progression
    type: add_comment
    weight: 25
    description: "Commentaire de suivi d'un DEV sur une Story en IN PROGRESS"
    constraints:
      issue_types: ["Story", "Feature"]
      statuses: ["IN PROGRESS"]
      actor_roles: ["DEV", "lead"]

  - id: synthese_epic
    type: add_comment
    weight: 12
    description: "Commentaire de suivi du Lead sur une Epic en cours"
    constraints:
      issue_types: ["Epic"]
      statuses: ["IN PROGRESS", "TO DO", "IDEA"]
      actor_roles: ["lead", "BA"]

  - id: engagement
    type: change_status
    weight: 20
    description: "Passage d'un ticket de TO DO / IDEA à IN PROGRESS"
    constraints:
      issue_types: ["Story", "Bug", "Task", "Feature", "Epic"]
      statuses: ["TO DO", "IDEA"]
      target_status: "IN PROGRESS"
      actor_roles: ["DEV", "lead", "BA"]

  - id: demande_review
    type: change_status
    weight: 15
    description: "Passage de IN PROGRESS à IN REVIEW — DEV ou Lead uniquement"
    constraints:
      issue_types: ["Story", "Bug", "Feature"]
      statuses: ["IN PROGRESS"]
      target_status: "IN REVIEW"
      actor_roles: ["DEV", "lead"]

  - id: finalisation
    type: change_status
    weight: 12
    description: "Passage de IN REVIEW à DONE — QA, BA ou Lead uniquement"
    constraints:
      issue_types: ["Story", "Bug", "Task", "Feature"]
      statuses: ["IN REVIEW"]
      target_status: "DONE"
      actor_roles: ["QA", "BA", "lead"]
      guard: "no_open_subtasks"

  - id: precision_qa
    type: add_comment
    weight: 10
    description: "Commentaire d'un QA sur un ticket en IN REVIEW"
    constraints:
      issue_types: ["Story", "Bug", "Feature"]
      statuses: ["IN REVIEW"]
      actor_roles: ["QA", "lead"]

  - id: blocage
    type: change_status
    weight: 8
    description: "Passage au statut BLOCKED avec commentaire IA obligatoire"
    constraints:
      issue_types: ["Story", "Bug", "Feature"]
      statuses: ["IN PROGRESS", "IN REVIEW"]
      target_status: "BLOCKED"
      actor_roles: ["DEV", "QA", "lead"]
      requires_ai_comment: true

  - id: passage_de_relais
    type: change_assignee
    weight: 10
    description: "Réassignation d'un ticket en cours à un autre membre"
    constraints:
      issue_types: ["Story", "Bug", "Task", "Feature"]
      statuses: ["IN PROGRESS", "IN REVIEW", "BLOCKED"]
      actor_roles: ["lead", "DEV", "BA"]

  - id: affinement_backlog
    type: add_comment
    weight: 8
    description: "Commentaire d'affinement sur une Epic ou Story en TO DO / IDEA"
    constraints:
      issue_types: ["Epic", "Story", "Feature"]
      statuses: ["TO DO", "IDEA"]
      actor_roles: ["lead", "BA"]
```

---

## CORRECTION 3 — Bootstrap dynamique avant chaque simulation

### 3.1 Rendre les projets configurables dans `.env`

Ajouter dans `.env.example` (et dans le `.env` réel) :

```env
# Projets à simuler — séparés par des virgules
JIRA_PROJECT_KEYS=POT,KAN

# Bootstrap automatique avant chaque run (true/false)
AUTO_BOOTSTRAP=true
```

### 3.2 Mettre à jour `bootstrap_state.py` pour supporter plusieurs projets

Modifier `bootstrap()` pour accepter une liste de clés de projets
et agréger tous leurs tickets dans un seul `state.json` :

```python
def bootstrap(project_keys: list[str], force_dry_run: bool = False) -> None:
    """
    Reconstruit state.json depuis Jira pour une liste de projets.
    Les membres sont toujours pris depuis config/teams.yaml.
    """
    jira = JiraClient(force_dry_run=force_dry_run)
    state_mgr = StateManager()

    with open('config/teams.yaml', 'r', encoding='utf-8') as f:
        teams_config = yaml.safe_load(f)

    # Construire les membres depuis teams.yaml (source de vérité unique)
    # Déduplication : un même member_id dans plusieurs équipes → team_ids liste
    members: dict = {}
    for team in teams_config.get('teams', []):
        for m in team.get('members', []):
            mid = m['id']
            if mid in members:
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

    # Agréger les tickets de tous les projets
    all_tickets: dict = {}
    for project_key in project_keys:
        logger.info("Bootstrap — récupération des tickets pour %s...", project_key)
        # Trouver l'équipe associée à ce projet (première équipe dont jira_project_key match)
        team_id = _find_team_for_project(project_key, teams_config)
        tickets_raw = jira.get_tickets_for_project(project_key=project_key)
        for t in tickets_raw:
            t['team_id'] = team_id
            all_tickets[t['key']] = t
        logger.info("  → %d ticket(s) récupéré(s) pour %s (équipe: %s)",
                    len(tickets_raw), project_key, team_id)

    state = {
        'last_run': None,
        'members': members,
        'tickets': all_tickets
    }
    state_mgr.save(state)
    logger.info("Bootstrap terminé — %d ticket(s) total, %d membre(s)",
                len(all_tickets), len(members))

    # Afficher un résumé par type de ticket
    from collections import Counter
    type_counts = Counter(t.get('issue_type', '?') for t in all_tickets.values())
    for itype, count in sorted(type_counts.items()):
        logger.info("  %s : %d ticket(s)", itype, count)


def _find_team_for_project(project_key: str, teams_config: dict) -> str:
    """Trouve l'équipe associée à un project_key via jira_project_key dans teams.yaml.
    Fallback sur la première équipe si non trouvé."""
    for team in teams_config.get('teams', []):
        if team.get('jira_project_key', '').upper() == project_key.upper():
            return team['id']
    # Fallback : première équipe
    teams = teams_config.get('teams', [])
    return teams[0]['id'] if teams else 'phoenix'
```

Mettre à jour `if __name__ == '__main__'` dans `bootstrap_state.py` :

```python
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bootstrap state depuis Jira')
    parser.add_argument(
        '--projects',
        default=os.getenv('JIRA_PROJECT_KEYS', os.getenv('JIRA_PROJECT_KEY', 'POT')),
        help='Clés de projets séparées par des virgules (ex: POT,KAN)'
    )
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    project_list = [p.strip() for p in args.projects.split(',') if p.strip()]
    bootstrap(project_list, force_dry_run=args.dry_run)
```

### 3.3 Mettre à jour `jira_client.get_tickets_for_project()` pour accepter un `project_key` paramètre

La méthode utilise actuellement `self.project_key` (valeur unique depuis `.env`).
Elle doit accepter un paramètre optionnel pour les appels multi-projets :

```python
def get_tickets_for_project(self,
                             project_key: str | None = None) -> list[dict]:
    """Récupère les tickets ouverts. project_key override self.project_key si fourni."""
    key = project_key or self.project_key

    if self.dry_run:
        return [
            {'key': f'{key}-1', 'summary': 'Setup CI pipeline',
             'issue_type': 'Story', 'status': 'IN PROGRESS',
             'status_category': 'IN PROGRESS', 'priority': 'High',
             'assignee_id': '', 'is_blocked': False,
             'epic_key': None, 'parent_key': None,
             'subtask_keys': [], 'linked_issues': [],
             'story_points': 5, 'last_updated': None},
            {'key': f'{key}-2', 'summary': 'Implement authentication',
             'issue_type': 'Epic', 'status': 'TO DO',
             'status_category': 'TO DO', 'priority': 'High',
             'assignee_id': '', 'is_blocked': False,
             'epic_key': None, 'parent_key': None,
             'subtask_keys': [], 'linked_issues': [],
             'story_points': None, 'last_updated': None},
            {'key': f'{key}-3', 'summary': 'Fix login timeout bug',
             'issue_type': 'Bug', 'status': 'IN REVIEW',
             'status_category': 'IN PROGRESS', 'priority': 'Medium',
             'assignee_id': '', 'is_blocked': False,
             'epic_key': None, 'parent_key': None,
             'subtask_keys': [], 'linked_issues': [],
             'story_points': 3, 'last_updated': None},
        ]

    url = f"{self.base_url}/rest/api/3/search/jql"
    payload = {
        "jql": (f"project = {key} "
                f"AND statusCategory != Done "
                f"ORDER BY updated DESC"),
        "maxResults": 100,
        "fields": [
            "summary", "status", "assignee", "issuetype",
            "priority", "parent", "subtasks", "issuelinks",
            "customfield_10016",   # story points
            "customfield_10014",   # epic link (classique)
            "customfield_10008"    # epic link (variante)
        ]
    }
    r = requests.post(url, headers=self._get_auth_headers(),
                      json=payload, timeout=15)
    data = self._handle_response(r, f"get_tickets_for_project({key})")

    tickets = []
    sm = StateManager()
    for issue in data.get('issues', []):
        fields = issue.get('fields', {})
        assignee = fields.get('assignee') or {}
        raw_status = fields.get('status', {}).get('name', 'TO DO')
        status_name = raw_status.strip().upper()   # normalisation immédiate

        # Résolution de l'epic parent
        epic_key = None
        parent_key = None
        parent = fields.get('parent')
        if parent:
            parent_type = (parent.get('fields', {})
                           .get('issuetype', {}).get('name', ''))
            if parent_type == 'Epic':
                epic_key = parent.get('key')
            else:
                parent_key = parent.get('key')
        # Fallback : champs custom epic link
        if not epic_key:
            epic_key = (fields.get('customfield_10014')
                        or fields.get('customfield_10008'))

        subtask_keys = [s['key'] for s in fields.get('subtasks', [])]

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

        story_points = (fields.get('customfield_10016')
                        or fields.get('customfield_10028'))

        tickets.append({
            'key': issue['key'],
            'summary': fields.get('summary', ''),
            'issue_type': fields.get('issuetype', {}).get('name', 'Story'),
            'status': status_name,
            'status_category': sm.get_status_category(status_name),
            'priority': fields.get('priority', {}).get('name', 'Medium'),
            'assignee_id': assignee.get('accountId', ''),
            'epic_key': epic_key,
            'parent_key': parent_key,
            'subtask_keys': subtask_keys,
            'linked_issues': linked_issues,
            'story_points': story_points,
            'is_blocked': False,
            'last_updated': None
        })

    logger.info("get_tickets_for_project(%s) : %d ticket(s)", key, len(tickets))
    return tickets
```

### 3.4 Ajouter `jira_project_key` dans `config/teams.yaml`

Pour que `_find_team_for_project` puisse mapper projet → équipe,
ajouter `jira_project_key` dans chaque équipe de `teams.yaml` :

```yaml
teams:
  - id: phoenix
    name: "Team Phoenix"
    jira_project_key: "POT"      # ← ajouter ce champ
    members:
      ...

  - id: nebula
    name: "Team Nebula"
    jira_project_key: "POT"      # même projet, équipe différente
    members:                      # (ou un autre project_key si multi-projets)
      ...
```

### 3.5 Bootstrap automatique dans `scheduler.py`

Mettre à jour `run_simulation` pour déclencher un bootstrap si `AUTO_BOOTSTRAP=true`
dans `.env` :

```python
def run_simulation(n_events: int = 3, force_dry_run: bool = False) -> None:
    """Lance la simulation — bootstrap automatique si AUTO_BOOTSTRAP=true."""

    # Bootstrap automatique si configuré
    auto_bootstrap = os.getenv('AUTO_BOOTSTRAP', 'false').lower() == 'true'
    if auto_bootstrap:
        from bootstrap_state import bootstrap
        project_keys_raw = os.getenv('JIRA_PROJECT_KEYS',
                                     os.getenv('JIRA_PROJECT_KEY', 'POT'))
        project_list = [p.strip() for p in project_keys_raw.split(',')
                        if p.strip()]
        logger.info("AUTO_BOOTSTRAP=true — rafraîchissement du state depuis Jira...")
        bootstrap(project_list, force_dry_run=force_dry_run)
        logger.info("Bootstrap terminé — state.json à jour")

    state_manager = StateManager()
    state = state_manager.load() or {'last_run': None, 'members': {}, 'tickets': {}}
    # ... reste de la fonction inchangée
```

---

## CORRECTION 4 — Logs enrichis avec la clé Jira pour le debug

### 4.1 Dans `scenario_engine.py` — logguer la clé et le type à la sélection

Dans `build_event`, après avoir choisi le ticket et le membre, ajouter
un log détaillé avant le `return` :

```python
logger.info(
    "Scénario '%s' → ticket %s [%s] statut '%s' assigné à %s (%s)",
    scenario.get('id'),
    ticket['key'],
    ticket.get('issue_type', '?'),
    ticket.get('status', '?'),
    member.get('display_name', member['id']),
    member.get('role', '?')
)
```

### 4.2 Dans `scheduler.py` — logguer le résultat de chaque événement

Dans la boucle, après l'exécution de chaque événement, remplacer
le log générique par un log précis :

```python
# Après exécution réussie, à la place du simple executed += 1 :
logger.info(
    "[OK] %s | %s %s | %s → %s | par %s",
    event.get('ticket_key', '?'),
    event.get('issue_type', '?'),
    f"({event.get('ticket_summary', '')[:40]})",
    event['context'].get('current_status', '?'),
    event['context'].get('target_status', '—'),
    event.get('member_name', '?')
)
executed += 1
```

Et en cas de skip, logguer pourquoi :

```python
# Dans le bloc if event is None :
logger.info(
    "[SKIP] scénario '%s' — aucun ticket/membre éligible",
    scenario.get('id', '?')
)
skipped += 1
```

---

## CORRECTION 5 — Ajouter `.env.example` mis à jour

Ajouter les deux nouvelles variables dans `.env.example` :

```env
# Projets à simuler — séparés par des virgules
JIRA_PROJECT_KEYS=POT

# Bootstrap automatique avant chaque run (true = rafraîchit state.json depuis Jira)
AUTO_BOOTSTRAP=true
```

Et dans le vrai `.env`, mettre :
```env
JIRA_PROJECT_KEYS=POT
AUTO_BOOTSTRAP=true
```

---

## Ordre d'exécution pour Copilot

1. Corriger `state_manager.get_status_category()` (Correction 1.1)
2. Corriger normalisation dans `bootstrap_state.py` (Correction 1.2)
3. Corriger comparaison dans `scenario_engine.build_event()` (Correction 1.3)
4. Remplacer `config/scenarios.yaml` — version avec Epics et Features (Correction 2)
5. Mettre à jour `bootstrap_state.py` — multi-projets + dédup membres (Correction 3.2)
6. Mettre à jour `jira_client.get_tickets_for_project()` — paramètre + normalisation (Correction 3.3)
7. Ajouter `jira_project_key` dans `config/teams.yaml` (Correction 3.4)
8. Mettre à jour `scheduler.py` — AUTO_BOOTSTRAP (Correction 3.5)
9. Ajouter les logs enrichis dans `scenario_engine.py` et `scheduler.py` (Correction 4)
10. Mettre à jour `.env.example` (Correction 5)
11. Lancer `python -m pytest -v` → tous les tests doivent passer
12. Lancer `python bootstrap_state.py --projects POT`
    → vérifier dans les logs que les types de tickets sont affichés (Epic: N, Story: N, Bug: N)
13. Lancer `python main.py --events 5 --dry-run`
    → vérifier que les logs affichent les clés Jira et que des scénarios sont retenus

---

## Sortie console attendue après correction

```
[INFO] AUTO_BOOTSTRAP=true — rafraîchissement du state depuis Jira...
[INFO] Bootstrap — récupération des tickets pour POT...
[INFO]   → 15 ticket(s) récupéré(s) pour POT (équipe: phoenix)
[INFO] Bootstrap terminé — 15 ticket(s) total, 5 membre(s)
[INFO]   Epic : 4 ticket(s)
[INFO]   Story : 8 ticket(s)
[INFO]   Bug : 3 ticket(s)
[INFO] AIWriter: using provider 'stub'
[INFO] JiraClient: DRY_RUN=True — aucun appel HTTP vers Jira
[INFO] Run started — 5 events requested
[INFO] Scénario 'engagement' → ticket POT-3 [Epic] statut 'TO DO' assigné à Lionel Dubois (lead)
[INFO] [OK] POT-3 | Epic (Refonte du module d'authentification) | TO DO → IN PROGRESS | par Lionel Dubois
[INFO] Scénario 'mise_a_jour_progression' → ticket POT-7 [Story] statut 'IN PROGRESS' assigné à Paul (DEV)
[INFO] [OK] POT-7 | Story (Implémentation OAuth 2.0) | IN PROGRESS → — | par Paul
[INFO] Run complete — 5 events executed, 0 skipped
[INFO] State saved to state.json
```

---

## Règles

- Ne pas modifier `main.py`
- Conserver tous les tests existants (11 doivent toujours passer)
- `load_dotenv()` reste en première instruction de tout point d'entrée
- Tous les statuts dans `state.json` doivent être en UPPERCASE après bootstrap
- Ne pas changer `DRY_RUN` dans `.env` — laisser la valeur actuelle
