# Prompt GitHub Copilot — Phase 5C : Équilibrage du backlog + distribution homogène
# Jira Activity Simulator — Maintien de la cohérence du backlog simulé

---

## Contexte et état actuel

Analyse du `state.json` actuel (21 tickets actifs après bootstrap) :

**Problèmes identifiés :**
1. **0 ticket en TO DO / IDEA** — les scénarios `engagement` et `affinement_backlog`
   n'ont aucun candidat, ils skipent systématiquement.
2. **8 tickets avec summary "Aucun contenu stub disponible pour ce type."**
   — les scénarios `create_issue` utilisaient `ai_content` comme summary
   mais le stub ne génère pas de texte pour le type `create_issue`.
3. **Majorité de tickets sans `epic_key`** — les scénarios `alimentation_produit`
   et `decomposition` manquent de contexte hiérarchique.
4. **Distribution homogène manquante** — le sélecteur de tickets ne pondère pas
   par projet ni par ticket, certains tickets reçoivent tous les événements.
5. **Epics non recréées automatiquement** quand le stock descend sous 10.

---

## PARTIE 1 — Corriger le summary des tickets créés par le simulateur

### 1.1 Enrichir `StubProvider` pour les types `create_issue` et `create_subtask`

Dans `providers/stub_provider.py`, ajouter des réponses pour les types
qui produisaient `"Aucun contenu stub disponible pour ce type."` :

```python
STUB_RESPONSES = {
    # ... réponses existantes ...

    'create_issue': [
        "Anomalie détectée sur le module de paiement — comportement inattendu en production.",
        "Régression sur l'authentification après déploiement v2.3.1.",
        "Performance dégradée sur l'endpoint /api/orders depuis ce matin.",
        "Erreur 500 intermittente sur la page de profil utilisateur.",
        "Problème de synchronisation entre le cache Redis et la base de données.",
        "Correctif nécessaire sur la gestion des timeouts réseau.",
        "Nouveau besoin identifié lors de la démo client — à planifier.",
        "Optimisation requise sur le pipeline de traitement des fichiers.",
    ],
    'create_subtask': [
        "Écrire les tests unitaires pour la nouvelle fonctionnalité.",
        "Documenter l'API et mettre à jour le swagger.",
        "Valider le comportement en environnement de staging.",
        "Revoir la gestion des cas d'erreur dans le module.",
        "Optimiser la requête SQL identifiée comme lente.",
        "Intégrer le retour de review dans le code.",
    ],
    'create_link': [
        "Lien de dépendance créé — en attente de la résolution du ticket bloquant.",
        "Relation identifiée entre ces deux tickets lors de l'affinement.",
    ],
    'update_field': [
        "Repriorisation suite aux retours du client.",
        "Estimation révisée après découverte de la complexité réelle.",
        "Mise à jour de la priorité après discussion avec le PO.",
    ],
}
```

### 1.2 Utiliser le stub `create_issue` comme summary dans `scheduler.py`

Dans la branche `create_issue` de `scheduler.py`, s'assurer que le summary
est construit proprement et tronqué à 200 caractères maximum (limite Jira) :

```python
elif stype == 'create_issue':
    # Générer un summary propre via le provider IA
    raw_content = event.get('ai_content') or ''
    # Prendre la première phrase comme summary (jusqu'au premier point ou 100 chars)
    summary = raw_content.split('.')[0].strip()[:100] or f"[{issue_type}] Nouveau ticket"
    # ...
```

---

## PARTIE 2 — Maintien du backlog TO DO (règle des 10 tickets minimum)

### 2.1 Créer `backlog_manager.py` à la racine

Ce module est appelé par le scheduler avant chaque run pour s'assurer
qu'il existe toujours suffisamment de tickets en TO DO et d'Epics actives :

```python
"""
Gestionnaire d'équilibre du backlog.
Crée automatiquement des tickets TO DO et des Epics si le stock est insuffisant.
"""
import os
import random
import logging
from dotenv import load_dotenv

load_dotenv()

from state_manager import StateManager
from jira_client import JiraClient
from ai_writer import AIWriter

logger = logging.getLogger(__name__)

# Seuils configurables via .env
MIN_TODO_TICKETS   = int(os.getenv('MIN_TODO_TICKETS', '10'))
MIN_ACTIVE_EPICS   = int(os.getenv('MIN_ACTIVE_EPICS', '10'))

# Summaries de secours si le provider IA échoue
FALLBACK_STORIES = [
    "Amélioration de l'expérience utilisateur sur le tableau de bord",
    "Mise en place des alertes de monitoring sur les APIs critiques",
    "Refactoring du module de gestion des permissions",
    "Documentation technique des composants principaux",
    "Optimisation du temps de chargement des pages lourdes",
    "Revue et mise à jour des dépendances de sécurité",
    "Implémentation du cache sur les endpoints à forte charge",
    "Correction des warnings de lint accumulés",
    "Ajout des tests d'intégration manquants",
    "Mise à jour du runbook de production",
    "Analyse des métriques de performance du mois",
    "Nettoyage des données obsolètes en base",
]

FALLBACK_EPICS = [
    "Modernisation de l'interface utilisateur",
    "Amélioration de la résilience système",
    "Programme de réduction de la dette technique",
    "Initiative qualité et couverture de tests",
    "Optimisation des coûts d'infrastructure",
    "Sécurisation des accès et des données",
    "Automatisation des processus manuels récurrents",
    "Migration vers l'architecture micro-services",
    "Amélioration de l'observabilité et du monitoring",
    "Programme d'onboarding et de documentation",
]


def check_and_replenish(project_keys: list[str],
                         jira_client: JiraClient,
                         state_manager: StateManager,
                         ai_writer: AIWriter,
                         teams_config: dict,
                         dry_run: bool = False) -> dict:
    """
    Vérifie les seuils et crée les tickets manquants.
    Retourne un résumé des créations effectuées.
    """
    state = state_manager.load()
    tickets = state.get('tickets', {})
    members = state.get('members', {})

    # Compter les tickets TO DO par projet
    todo_by_project: dict[str, int] = {k: 0 for k in project_keys}
    epics_by_project: dict[str, int] = {k: 0 for k in project_keys}

    for ticket in tickets.values():
        key_prefix = ticket['key'].split('-')[0]
        if key_prefix not in todo_by_project:
            continue
        if ticket.get('status_category') == 'TO DO':
            todo_by_project[key_prefix] += 1
        if (ticket.get('issue_type') == 'Epic'
                and ticket.get('status_category') != 'DONE'):
            epics_by_project[key_prefix] += 1

    created_stories = 0
    created_epics   = 0

    # Leads disponibles pour assigner les nouveaux tickets
    leads = [mid for mid, data in members.items()
             if data.get('role', '').lower() == 'lead'
             and data.get('availability') == 'available']
    default_lead = leads[0] if leads else None

    for project_key in project_keys:
        # Trouver l'équipe du projet
        team_id = _find_team_for_project(project_key, teams_config)
        lead_id = _find_lead_for_team(team_id, members) or default_lead

        # 1. Créer des Epics si nécessaire
        epics_needed = max(0, MIN_ACTIVE_EPICS - epics_by_project[project_key])
        for i in range(epics_needed):
            summary = random.choice(FALLBACK_EPICS)
            account_id = members.get(lead_id, {}).get('jira_account_id', '') if lead_id else ''
            fields = {
                'project': {'key': project_key},
                'summary': summary,
                'issuetype': {'name': 'Epic'},
                'priority': {'name': 'Medium'},
            }
            if account_id:
                fields['assignee'] = {'accountId': account_id}
            result = jira_client.create_issue(fields)
            if result.get('key') or dry_run:
                created_epics += 1
                logger.info(
                    "[BACKLOG] Epic créée dans %s : '%s'",
                    project_key, summary
                )

        # 2. Créer des Stories TO DO si nécessaire
        # Récupérer les Epics actives pour rattacher les nouvelles Stories
        active_epics = [
            k for k, t in tickets.items()
            if t.get('issue_type') == 'Epic'
            and t.get('status_category') != 'DONE'
            and k.startswith(project_key + '-')
        ]

        stories_needed = max(0, MIN_TODO_TICKETS - todo_by_project[project_key])
        for i in range(stories_needed):
            summary = random.choice(FALLBACK_STORIES)
            # 80% des Stories rattachées à une Epic
            epic_key = None
            if active_epics and random.random() < 0.80:
                epic_key = random.choice(active_epics)

            fields = {
                'project': {'key': project_key},
                'summary': summary,
                'issuetype': {'name': 'Story'},
                'priority': {'name': random.choice(['Low', 'Medium', 'High'])},
            }
            if epic_key:
                fields['parent'] = {'key': epic_key}

            result = jira_client.create_issue(fields)
            if result.get('key') or dry_run:
                created_stories += 1
                logger.info(
                    "[BACKLOG] Story TO DO créée dans %s%s : '%s'",
                    project_key,
                    f" (Epic: {epic_key})" if epic_key else "",
                    summary
                )

    summary_result = {
        'epics_created': created_epics,
        'stories_created': created_stories,
        'todo_by_project': todo_by_project,
        'epics_by_project': epics_by_project,
    }
    if created_epics or created_stories:
        logger.info(
            "[BACKLOG] Rééquilibrage : +%d Epic(s), +%d Story(ies) TO DO",
            created_epics, created_stories
        )
    else:
        logger.info("[BACKLOG] Backlog équilibré — aucune création nécessaire")

    return summary_result


def _find_team_for_project(project_key: str, teams_config: dict) -> str:
    for team in teams_config.get('teams', []):
        if team.get('jira_project_key', '').upper() == project_key.upper():
            return team['id']
    teams = teams_config.get('teams', [])
    return teams[0]['id'] if teams else 'phoenix'


def _find_lead_for_team(team_id: str, members: dict) -> str | None:
    for mid, data in members.items():
        if (data.get('role', '').lower() == 'lead'
                and team_id in data.get('team_ids', [])):
            return mid
    return None
```

### 2.2 Ajouter les variables dans `.env.example`

```env
# Seuils de maintien du backlog
MIN_TODO_TICKETS=10
MIN_ACTIVE_EPICS=10

# Rééquilibrage automatique avant chaque run (true/false)
AUTO_REPLENISH=true
```

### 2.3 Intégrer `backlog_manager` dans `scheduler.py`

Après le bootstrap automatique et avant la boucle d'événements,
appeler `check_and_replenish` si `AUTO_REPLENISH=true` :

```python
# Dans run_simulation(), après le bloc AUTO_BOOTSTRAP :
auto_replenish = os.getenv('AUTO_REPLENISH', 'false').lower() == 'true'
if auto_replenish:
    import yaml
    from backlog_manager import check_and_replenish
    with open('config/teams.yaml', 'r', encoding='utf-8') as f:
        teams_cfg = yaml.safe_load(f)
    project_keys_raw = os.getenv('JIRA_PROJECT_KEYS',
                                  os.getenv('JIRA_PROJECT_KEY', 'POT'))
    project_list = [p.strip() for p in project_keys_raw.split(',')
                    if p.strip()]
    check_and_replenish(
        project_list, jira_client, state_manager,
        ai_writer, teams_cfg, dry_run=force_dry_run
    )
    # Recharger le state après la création des nouveaux tickets
    state = state_manager.load()
```

---

## PARTIE 3 — Distribution homogène des événements

### 3.1 Anti-répétition dans `scenario_engine.py`

**Problème** : `random.choice(candidates)` favorise les tickets qui reviennent
souvent dans la liste (pas de pondération par fraîcheur).

**Correction** : pondérer le choix du ticket par l'ancienneté de `last_updated`
— les tickets les moins récemment touchés ont plus de chances d'être sélectionnés :

```python
def _pick_ticket_weighted(self, candidates: list[dict]) -> dict:
    """
    Choisit un ticket en favorisant ceux non touchés récemment.
    Un ticket sans last_updated ou mis à jour il y a longtemps a plus de poids.
    """
    import datetime
    import random

    now = datetime.datetime.utcnow()
    weights = []
    for ticket in candidates:
        last = ticket.get('last_updated')
        if not last:
            # Jamais touché = poids maximum
            weights.append(100)
        else:
            try:
                dt = datetime.datetime.fromisoformat(last)
                age_hours = max(1, (now - dt).total_seconds() / 3600)
                # Poids proportionnel à l'ancienneté, plafonné à 100
                weights.append(min(100, int(age_hours)))
            except ValueError:
                weights.append(50)

    return random.choices(candidates, weights=weights, k=1)[0]
```

Remplacer `random.choice(candidates)` par `self._pick_ticket_weighted(candidates)`
dans `build_event`.

### 3.2 Distribution équitable entre projets

Dans `build_event`, quand plusieurs projets sont présents dans le state,
éviter que tous les événements atterrissent sur le même projet.
Implémenter une rotation par projet en utilisant un compteur persistant
dans le state :

```python
def _pick_project_balanced(self, candidates: list[dict],
                            state: dict) -> list[dict]:
    """
    Filtre les candidats pour favoriser le projet le moins récemment actif.
    Retourne une sous-liste des candidats du projet prioritaire.
    """
    import collections
    # Compter les last_updated récents par projet
    project_activity: dict[str, float] = collections.defaultdict(float)
    import datetime
    now = datetime.datetime.utcnow()
    for ticket in state.get('tickets', {}).values():
        last = ticket.get('last_updated')
        if last:
            try:
                dt = datetime.datetime.fromisoformat(last)
                age = (now - dt).total_seconds()
                proj = ticket['key'].split('-')[0]
                # Accumuler l'activité récente (plus c'est récent, plus c'est élevé)
                project_activity[proj] += max(0, 86400 - age)
            except ValueError:
                pass

    # Identifier les projets représentés dans les candidats
    candidate_projects = list({t['key'].split('-')[0] for t in candidates})
    if len(candidate_projects) <= 1:
        return candidates

    # Choisir le projet le moins actif récemment
    least_active = min(candidate_projects,
                       key=lambda p: project_activity.get(p, 0))

    filtered = [t for t in candidates
                if t['key'].split('-')[0] == least_active]
    # Si aucun candidat dans ce projet après filtrage, retourner tous les candidats
    return filtered if filtered else candidates
```

Appeler `_pick_project_balanced` avant `_pick_ticket_weighted` dans `build_event` :

```python
# Dans build_event, remplacer :
# ticket = random.choice(candidates)
# par :
balanced_candidates = self._pick_project_balanced(candidates, state)
ticket = self._pick_ticket_weighted(balanced_candidates)
```

---

## PARTIE 4 — Rattachement automatique aux Epics au bootstrap

### 4.1 Dans `bootstrap_state.py` — rattacher les tickets orphelins

Après la normalisation de tous les tickets, faire un second passage
pour rattacher les Stories sans `epic_key` à une Epic active du même projet :

```python
# Dans bootstrap(), après la construction de all_tickets :
_attach_orphans_to_epics(all_tickets)


def _attach_orphans_to_epics(tickets: dict) -> None:
    """
    Rattache les Stories et Bugs sans epic_key à une Epic active
    du même projet (80% de probabilité — laisse 20% d'orphelins volontaires).
    """
    import random
    # Indexer les Epics actives par projet
    epics_by_project: dict[str, list[str]] = {}
    for key, ticket in tickets.items():
        if (ticket.get('issue_type') == 'Epic'
                and ticket.get('status_category') != 'DONE'):
            proj = key.split('-')[0]
            epics_by_project.setdefault(proj, []).append(key)

    # Rattacher les orphelins
    for key, ticket in tickets.items():
        if ticket.get('issue_type') not in ('Story', 'Bug', 'Feature'):
            continue
        if ticket.get('epic_key'):
            continue   # déjà rattaché
        proj = key.split('-')[0]
        available_epics = epics_by_project.get(proj, [])
        if available_epics and random.random() < 0.80:
            ticket['epic_key'] = random.choice(available_epics)
```

---

## PARTIE 5 — Tests à ajouter

### `tests/test_backlog_manager.py`

```python
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
```

### `tests/test_scenario_distribution.py`

```python
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
```

---

## Ordre d'exécution pour Copilot

1. **Partie 1** : enrichir `StubProvider` avec les nouveaux types
   + corriger le summary dans la branche `create_issue` de `scheduler.py`
2. **Partie 2** : créer `backlog_manager.py`
   + ajouter `MIN_TODO_TICKETS`, `MIN_ACTIVE_EPICS`, `AUTO_REPLENISH` dans `.env.example`
   + intégrer dans `scheduler.py`
3. **Partie 3** : ajouter `_pick_ticket_weighted` et `_pick_project_balanced`
   dans `scenario_engine.py` + remplacer `random.choice`
4. **Partie 4** : ajouter `_attach_orphans_to_epics` dans `bootstrap_state.py`
5. **Partie 5** : ajouter `tests/test_backlog_manager.py`
   et `tests/test_scenario_distribution.py`
6. `python -m pytest -v` → tous les tests doivent passer
7. Dans `.env`, mettre `AUTO_REPLENISH=true`, `MIN_TODO_TICKETS=10`, `MIN_ACTIVE_EPICS=10`
8. `python bootstrap_state.py --projects POT,KAN`
   → vérifier le résumé par type (doit montrer des Epic et Story)
9. `python main.py --events 10 --dry-run`
   → vérifier que les logs montrent des tickets des deux projets
   → vérifier qu'aucun summary ne contient "Aucun contenu stub"
   → vérifier que des tickets TO DO sont sélectionnés

---

## Sortie console attendue

```
[INFO] AUTO_BOOTSTRAP=true — rafraîchissement du state...
[INFO] Bootstrap terminé — 21 ticket(s), 5 membre(s)
[INFO]   Epic : 9 | Story : 7 | Bug : 3 | Task : 2
[INFO] AUTO_REPLENISH=true — vérification des seuils...
[INFO] [BACKLOG] Story TO DO créée dans POT (Epic: POT-19) : 'Mise en place des alertes...'
[INFO] [BACKLOG] Story TO DO créée dans KAN : 'Analyse des métriques de performance...'
[INFO] [BACKLOG] Rééquilibrage : +0 Epic(s), +8 Story(ies) TO DO
[INFO] Run started — 10 events requested
[INFO] Scénario 'engagement' → ticket POT-31 [Story] statut 'TO DO' assigné à Paul (DEV)
[INFO] [OK] POT-31 | Story (Mise en place des alertes...) | TO DO → IN PROGRESS | par Paul
[INFO] Scénario 'synthese_epic' → ticket KAN-1 [Epic] statut 'IN PROGRESS' assigné à Lionel (lead)
[INFO] [OK] KAN-1 | Epic (Franchise Marvel) | IN PROGRESS → — | par Lionel Dubois
[INFO] Run complete — 10 events executed, 0 skipped
[INFO] State saved to state.json
```

---

## Règles

- Python 3.11+, type hints, docstrings en français
- `backlog_manager.py` ne modifie pas directement le state — il délègue
  à `jira_client.create_issue()` et laisse le prochain bootstrap sync le state
- En mode `--dry-run`, `backlog_manager` logue les créations sans appeler Jira
- Conserver tous les tests existants (11+ doivent passer)
- Ne pas modifier `main.py`
- `load_dotenv()` en première instruction de tout module avec `os.getenv()`
