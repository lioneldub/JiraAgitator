# Prompt GitHub Copilot — Phase 1 : Squelette & environnement
# Jira Activity Simulator — Architecture B modulaire

---

## Contexte du projet

Je construis un simulateur d'activité Jira Cloud en Python.
Il tournera en cron job et simulera l'activité de plusieurs équipes Scrum :
changements de statut de tickets, réassignations, commentaires, blocages, absences, etc.
Le contenu textuel (commentaires, descriptions) sera généré par une IA.

L'architecture est modulaire (option B) avec les composants suivants :
- `config/` : fichiers YAML décrivant les équipes et les scénarios
- `state.json` : état courant des tickets et disponibilités des membres
- `scheduler.py` : point d'entrée, orchestre les runs
- `scenario_engine.py` : choisit et construit l'événement à jouer
- `ai_writer.py` : génère le contenu textuel (stub en phase 1)
- `jira_client.py` : exécute les appels REST Jira (dry-run en phase 1)

---

## Ce que je veux que tu génères

### 1. Structure de dossiers complète

Crée l'arborescence suivante, avec tous les fichiers listés :

```
jira-simulator/
├── config/
│   ├── teams.yaml
│   └── scenarios.yaml
├── providers/
│   ├── __init__.py
│   └── stub_provider.py
├── tests/
│   ├── __init__.py
│   └── test_scenario_engine.py
├── .env.example
├── .gitignore
├── main.py
├── scheduler.py
├── scenario_engine.py
├── ai_writer.py
├── jira_client.py
├── state_manager.py
├── requirements.txt
└── README.md
```

---

### 2. Contenu des fichiers

#### `config/teams.yaml`

Définit 2 équipes fictives avec 3 à 4 membres chacune.
Chaque membre a : `id`, `display_name`, `role` (dev/qa/lead), `availability` (available/absent).
Exemple de noms : équipe "Phoenix" et équipe "Nebula".

```yaml
teams:
  - id: phoenix
    name: "Team Phoenix"
    members:
      - id: alice_m
        display_name: "Alice Martin"
        role: lead
        availability: available
      - id: bob_d
        display_name: "Bob Dupont"
        role: dev
        availability: available
      - id: claire_v
        display_name: "Claire Vidal"
        role: dev
        availability: available
      - id: david_r
        display_name: "David Renard"
        role: qa
        availability: available

  - id: nebula
    name: "Team Nebula"
    members:
      - id: emma_b
        display_name: "Emma Bernard"
        role: lead
        availability: available
      - id: felix_g
        display_name: "Félix Garcia"
        role: dev
        availability: available
      - id: grace_l
        display_name: "Grace Lambert"
        role: dev
        availability: available
```

#### `config/scenarios.yaml`

Définit les types d'événements simulables avec leur poids de probabilité.
Chaque scénario a : `id`, `type`, `weight` (int, somme libre), `description`.

Types à inclure :
- `add_comment` — un membre commente un ticket
- `change_status` — un ticket change de statut (To Do → In Progress → In Review → Done)
- `change_assignee` — réassignation d'un ticket
- `block_ticket` — un ticket est marqué comme bloqué avec un commentaire d'explication
- `set_absence` — un membre passe en absent, ses tickets sont réassignés
- `return_from_absence` — un membre revient, redevient disponible
- `add_subtask` — création d'une sous-tâche sur un ticket existant

```yaml
scenarios:
  - id: add_comment
    type: add_comment
    weight: 40
    description: "Un membre de l'équipe ajoute un commentaire de suivi sur un ticket"

  - id: change_status
    type: change_status
    weight: 30
    description: "Un ticket avance dans le workflow (To Do → In Progress → In Review → Done)"

  - id: change_assignee
    type: change_assignee
    weight: 10
    description: "Un ticket est réassigné à un autre membre de l'équipe"

  - id: block_ticket
    type: block_ticket
    weight: 8
    description: "Un ticket est bloqué — le membre explique le blocage en commentaire"

  - id: set_absence
    type: set_absence
    weight: 4
    description: "Un membre part en absence, ses tickets ouverts sont réassignés"

  - id: return_from_absence
    type: return_from_absence
    weight: 4
    description: "Un membre revient d'absence et redevient disponible"

  - id: add_subtask
    type: add_subtask
    weight: 4
    description: "Une sous-tâche est créée sur un ticket existant"
```

#### `state_manager.py`

Classe `StateManager` qui gère `state.json`.

Méthodes requises :
- `load() -> dict` : charge state.json, retourne `{}` si absent
- `save(state: dict)` : écrit state.json avec indentation
- `get_available_members(team_id: str) -> list` : retourne les membres disponibles d'une équipe
- `get_open_tickets(team_id: str) -> list` : retourne les tickets non-Done d'une équipe
- `update_member_availability(member_id: str, status: str)` : modifie la dispo d'un membre
- `update_ticket_status(ticket_key: str, new_status: str)` : met à jour le statut d'un ticket
- `update_ticket_assignee(ticket_key: str, new_assignee_id: str)` : réassigne un ticket

Format de `state.json` à respecter :
```json
{
  "last_run": null,
  "members": {
    "alice_m": { "availability": "available", "current_tickets": [] },
    "bob_d":   { "availability": "available", "current_tickets": [] }
  },
  "tickets": {
    "PROJ-1": {
      "key": "PROJ-1",
      "summary": "Setup CI pipeline",
      "status": "In Progress",
      "assignee_id": "alice_m",
      "team_id": "phoenix",
      "is_blocked": false
    }
  }
}
```

#### `scenario_engine.py`

Classe `ScenarioEngine` qui :
1. Charge `config/scenarios.yaml` au démarrage
2. Méthode `pick_scenario() -> dict` : tire un scénario au sort selon les poids (utilise `random.choices`)
3. Méthode `build_event(scenario: dict, state: dict, teams_config: dict) -> dict | None` :
   - Choisit un membre disponible et un ticket cohérent avec le scénario
   - Retourne un dict `event` avec tous les champs nécessaires à l'exécution
   - Retourne `None` si aucun membre/ticket disponible pour ce scénario
4. Format d'un event retourné :
```python
{
    "type": "add_comment",          # type du scénario
    "team_id": "phoenix",
    "member_id": "alice_m",
    "member_name": "Alice Martin",
    "ticket_key": "PROJ-1",
    "ticket_summary": "Setup CI pipeline",
    "context": {                    # infos contextuelles pour le prompt IA
        "current_status": "In Progress",
        "is_blocked": False
    },
    "ai_content": None              # sera rempli par ai_writer
}
```

#### `providers/stub_provider.py`

Classe `StubProvider` avec une méthode `generate(event: dict) -> str`.
Elle retourne une réponse textuelle fixe selon le `event["type"]`.
Les réponses doivent être réalistes et en français, adaptées au type :

```python
STUB_RESPONSES = {
    "add_comment": [
        "Point de suivi : j'ai avancé sur la partie backend, les tests unitaires passent. Je continue demain sur l'intégration.",
        "RAS de mon côté, en attente du retour de l'équipe QA avant de passer en review.",
        "Petite complication sur la config Docker, je creuse ça cet après-midi."
    ],
    "change_status": [
        "Ticket déplacé en In Review — prêt pour la relecture.",
        "Passage en In Progress, je prends ce sujet.",
        "Ticket terminé, déployé en staging."
    ],
    "block_ticket": [
        "Ticket bloqué : dépendance non résolue côté API externe, en attente de réponse du fournisseur.",
        "Bloqué en attente de clarification des specs — j'ai pingé le PO.",
        "Blocage technique : la migration de base de données échoue sur l'environnement de test."
    ],
    "change_assignee": [
        "Réassigné suite à rééquilibrage de la charge.",
        "Je reprends ce ticket, l'ancien assignee est surchargé."
    ],
    "set_absence": [
        "Je serai absent jusqu'à nouvel ordre. Mes tickets sont réassignés.",
        "Absence imprévue — tickets transférés à l'équipe."
    ],
    "return_from_absence": [
        "De retour, je reprends mes activités normalement.",
    ],
    "add_subtask": [
        "Création d'une sous-tâche pour découper le travail restant.",
    ]
}
```
La méthode `generate()` choisit aléatoirement parmi les réponses disponibles pour le type.

#### `ai_writer.py`

Classe `AIWriter` qui :
- Prend `provider_name: str` en paramètre (`"stub"` par défaut, lira depuis `.env`)
- Charge le bon provider depuis `providers/`
- Méthode `generate_content(event: dict) -> str` : délègue au provider
- Loggue quel provider est utilisé au démarrage

```python
# Utilisation attendue
writer = AIWriter(provider_name=os.getenv("AI_PROVIDER", "stub"))
content = writer.generate_content(event)
```

#### `jira_client.py`

Classe `JiraClient` qui :
- Lit `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` depuis `.env`
- Lit `DRY_RUN` (bool, défaut `True`) depuis `.env`
- Si `DRY_RUN=true` : toutes les méthodes write loggent l'action sans appel HTTP, les reads retournent des fixtures
- Méthodes à implémenter :
  - `add_comment(ticket_key: str, body: str) -> dict`
  - `transition_ticket(ticket_key: str, new_status: str) -> dict`
  - `assign_ticket(ticket_key: str, account_id: str) -> dict`
  - `create_subtask(parent_key: str, summary: str, assignee_id: str) -> dict`
  - `get_tickets_for_project() -> list` : retourne des fixtures en dry-run

En dry-run, chaque méthode affiche :
```
[DRY-RUN] add_comment on PROJ-1 → "Point de suivi : j'ai avancé..."
```

#### `scheduler.py`

Fonction `run_simulation(n_events: int = 3)` qui :
1. Charge la config teams + scenarios
2. Instancie `StateManager`, `ScenarioEngine`, `AIWriter`, `JiraClient`
3. Boucle `n_events` fois :
   a. `pick_scenario()` → scénario
   b. `build_event()` → event ou None (si None, skip et log)
   c. `generate_content(event)` → remplit `event["ai_content"]`
   d. Appelle la bonne méthode de `JiraClient` selon `event["type"]`
   e. Met à jour le `StateManager`
4. Sauvegarde le state en fin de run
5. Affiche un résumé : N événements joués, N skippés

#### `main.py`

Point d'entrée minimal :
```python
import argparse
from scheduler import run_simulation

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira Activity Simulator")
    parser.add_argument("--events", type=int, default=3, help="Nombre d'événements à simuler")
    parser.add_argument("--dry-run", action="store_true", help="Force le mode dry-run")
    args = parser.parse_args()
    run_simulation(n_events=args.events)
```

#### `.env.example`

```env
# Provider IA : stub | gemini | groq
AI_PROVIDER=stub

# Jira Cloud
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-api-token-here
JIRA_PROJECT_KEY=PROJ

# Mode dry-run (true = aucun appel HTTP vers Jira)
DRY_RUN=true

# Nombre d'événements par run
EVENTS_PER_RUN=3
```

#### `requirements.txt`

```
pyyaml>=6.0
python-dotenv>=1.0
requests>=2.31
```

#### `.gitignore`

```
.env
state.json
__pycache__/
*.pyc
.venv/
venv/
*.egg-info/
dist/
.pytest_cache/
```

#### `tests/test_scenario_engine.py`

Tests unitaires avec `pytest` pour `ScenarioEngine` :
- `test_pick_scenario_returns_valid_type` : vérifie que le scénario retourné a un `type` valide
- `test_build_event_returns_none_when_no_members` : state vide → `build_event` retourne None
- `test_build_event_comment_has_all_fields` : event `add_comment` a tous les champs requis
- `test_stub_provider_returns_string_for_all_types` : vérifie que StubProvider couvre tous les types

#### `README.md`

README avec :
- Description du projet en 3 lignes
- Prérequis (Python 3.11+)
- Installation : `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Configuration : copier `.env.example` en `.env`, remplir les valeurs
- Lancement : `python main.py --events 5`
- Variables d'environnement documentées (tableau markdown)
- Section "Modes" : stub vs IA réelle, dry-run vs live

---

### 3. Règles de code à respecter

- Python 3.11+
- Type hints sur toutes les fonctions publiques
- Docstrings en français sur toutes les classes et méthodes publiques
- Logging avec le module standard `logging` (pas de `print` sauf dans dry-run display)
- Pas de dépendances externes sauf celles dans `requirements.txt`
- Chaque module est indépendamment importable et testable
- Les chemins de fichiers sont relatifs à la racine du projet (utiliser `pathlib.Path`)
- Les erreurs Jira (HTTP 4xx/5xx) sont catchées et loggées, elles n'interrompent pas le run

---

### 4. Vérification finale attendue

Une fois tout généré, la commande suivante doit fonctionner sans erreur :

```bash
python -m venv .venv
source .venv/bin/activate      # ou .venv\Scripts\activate sur Windows
pip install -r requirements.txt
cp .env.example .env
python main.py --events 5
```

La sortie console attendue ressemble à :

```
[INFO] AIWriter: using provider 'stub'
[INFO] JiraClient: DRY_RUN=True — no HTTP calls will be made
[INFO] Run started — 5 events requested

[DRY-RUN] add_comment on PROJ-1 → "Point de suivi : j'ai avancé sur la partie backend..."
[DRY-RUN] change_status on PROJ-2 → transition to 'In Review'
[DRY-RUN] add_comment on PROJ-3 → "RAS de mon côté, en attente du retour de l'équipe QA..."
[DRY-RUN] block_ticket on PROJ-1 → "Blocage technique : la migration de base de données..."
[INFO] Scenario 'set_absence' skipped — no available member found
[INFO] Scenario 'change_assignee' skipped — no ticket found for this event

[INFO] Run complete — 4 events executed, 2 skipped
[INFO] State saved to state.json
```

---

### 5. State initial à créer

Pour que le premier run fonctionne sans projet Jira réel, crée un `state.json` initial avec
5 tickets fictifs répartis sur les deux équipes (statuts variés : To Do, In Progress, In Review)
et tous les membres en `available`.
