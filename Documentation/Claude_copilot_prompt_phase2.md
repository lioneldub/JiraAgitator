# Prompt GitHub Copilot — Phase 2 : Provider pattern IA + JiraClient live + corrections
# Jira Activity Simulator — Suite de la phase 1

---

## Contexte et état actuel

La phase 1 est terminée et validée (`python main.py --events 5` fonctionne en dry-run).
Le projet est dans `c:\Users\User\Documents\devproject\JiraAgitator`.

Avant d'ajouter de nouvelles fonctionnalités, il faut corriger 5 dettes techniques
identifiées dans le code existant, puis implémenter le provider pattern IA et le
JiraClient live.

---

## PARTIE 1 — Corrections des dettes techniques (priorité absolue)

### 1.1 Ajouter `load_dotenv()` dans `scheduler.py`

**Problème** : `python-dotenv` est dans `requirements.txt` mais jamais appelé.
`os.getenv()` ne lit que les variables système — le fichier `.env` est totalement ignoré.

**Correction** : au tout début de `scheduler.py`, avant tout import de module projet :

```python
from dotenv import load_dotenv
load_dotenv()  # doit être appelé AVANT les instanciations qui lisent os.getenv()
```

Placer `load_dotenv()` comme première instruction exécutable du module,
avant `StateManager()`, `AIWriter()`, `JiraClient()`.

### 1.2 Corriger `AIWriter` — provider dynamique

**Problème** : `ai_writer.py` lit `AI_PROVIDER` depuis l'env mais instancie
`StubProvider()` inconditionnellement — le flag n'a aucun effet.

**Correction** : remplacer l'instanciation hardcodée par une factory :

```python
# ai_writer.py — version corrigée
import os
from typing import Any, Dict
from logging import getLogger

logger = getLogger(__name__)

class AIWriter:
    """Wrapper IA qui charge dynamiquement le provider selon AI_PROVIDER."""

    def __init__(self, provider_name: str | None = None) -> None:
        self.provider_name = provider_name or os.getenv('AI_PROVIDER', 'stub')
        self.provider = self._load_provider(self.provider_name)
        logger.info("AIWriter: using provider '%s'", self.provider_name)

    def _load_provider(self, name: str):
        """Instancie le bon provider selon le nom."""
        if name == 'stub':
            from providers.stub_provider import StubProvider
            return StubProvider()
        elif name == 'gemini':
            from providers.gemini_provider import GeminiProvider
            return GeminiProvider()
        elif name == 'groq':
            from providers.groq_provider import GroqProvider
            return GroqProvider()
        else:
            logger.warning("Provider '%s' inconnu, fallback sur stub", name)
            from providers.stub_provider import StubProvider
            return StubProvider()

    def generate_content(self, event: Dict[str, Any]) -> str:
        """Génère le contenu textuel pour l'événement via le provider."""
        return self.provider.generate(event)
```

### 1.3 Corriger `--dry-run` CLI dans `main.py`

**Problème** : l'argument `--dry-run` est parsé mais jamais transmis — il ne fait rien.

**Correction** : transmettre le flag à `run_simulation` et le propager au `JiraClient` :

```python
# main.py — version corrigée
import argparse
from scheduler import run_simulation

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Jira Activity Simulator')
    parser.add_argument('--events', type=int, default=3,
                        help='Nombre d\'evenements a simuler')
    parser.add_argument('--dry-run', action='store_true',
                        help='Force le mode dry-run (override .env)')
    args = parser.parse_args()
    run_simulation(n_events=args.events, force_dry_run=args.dry_run)
```

Mettre à jour la signature de `run_simulation` dans `scheduler.py` :
```python
def run_simulation(n_events: int = 3, force_dry_run: bool = False) -> None:
```
Et passer `force_dry_run` au constructeur `JiraClient(force_dry_run=force_dry_run)`.
`JiraClient.__init__` doit prendre `force_dry_run: bool = False` et faire :
```python
self.dry_run = force_dry_run or os.getenv('DRY_RUN', 'true').lower() == 'true'
```

### 1.4 Corriger `change_assignee` dans `scheduler.py`

**Problème** : la réassignation prend toujours `available_members[0]` — pas aléatoire,
et peut réassigner au membre déjà assigné.

**Correction** :
```python
elif stype == 'change_assignee':
    current_assignee = state.get('tickets', {}).get(key, {}).get('assignee_id')
    candidates = [
        x for x, v in state.get('members', {}).items()
        if v.get('availability') == 'available' and x != current_assignee
    ]
    if candidates:
        import random
        new_assignee = random.choice(candidates)
        jira_client.assign_ticket(key, new_assignee)
        state_manager.update_ticket_assignee(key, new_assignee)
        state = state_manager.load()  # recharger après mutation
```

### 1.5 Ajouter guard `DRY_RUN` dans `JiraClient` pour les méthodes live

**Problème** : les méthodes non-dry-run retournent `{}` silencieusement — si
`DRY_RUN=false` est activé par erreur, rien ne se passe et aucune erreur n'est levée.

**Correction** : dans chaque méthode write de `JiraClient`, remplacer `return {}` par :
```python
logger.error(
    "JiraClient.%s appelé en mode LIVE mais non implémenté — "
    "positionner DRY_RUN=true ou implémenter la méthode", action_name
)
raise NotImplementedError(f"{action_name} non implémenté en mode live")
```

---

## PARTIE 2 — Provider pattern IA

### 2.1 Interface commune `providers/base_provider.py`

Créer ce fichier avec une classe abstraite :

```python
from abc import ABC, abstractmethod
from typing import Dict

class BaseProvider(ABC):
    """Interface commune pour tous les providers IA."""

    @abstractmethod
    def generate(self, event: Dict) -> str:
        """Génère un texte à partir d'un événement."""
        ...
```

Mettre à jour `StubProvider` pour hériter de `BaseProvider`.

### 2.2 `providers/gemini_provider.py` — Gemini 2.0 Flash (gratuit)

Implémenter `GeminiProvider` avec :
- Dépendance : `google-generativeai>=0.5` (à ajouter dans `requirements.txt`)
- Clé API lue depuis `GEMINI_API_KEY` dans `.env`
- Modèle : `gemini-2.0-flash` (1500 req/jour gratuit)
- Méthode `generate(event: Dict) -> str` qui :
  1. Construit un prompt contextuel à partir de l'event (voir format ci-dessous)
  2. Appelle `genai.GenerativeModel("gemini-2.0-flash").generate_content(prompt)`
  3. Retourne `response.text`
  4. En cas d'exception, log l'erreur et retourne un texte stub de fallback

Format du prompt contextuel à construire :
```
Tu simules {member_name}, {role} dans l'équipe Scrum "{team_id}".
Tu travailles sur le ticket "{ticket_key} — {ticket_summary}" (statut actuel : {current_status}).
Action demandée : {description de l'event type en français}

Génère un message court (2-4 phrases maximum) en français, naturel et professionnel,
comme si tu étais vraiment ce développeur dans son outil de ticketing.
Ne commence pas par "Je" — varie les formulations.
Réponds uniquement avec le message, sans introduction ni explication.
```

Gérer le cas où `ticket_key` est None (événements absence) : adapter le prompt en conséquence.

Ajouter `GEMINI_API_KEY=your-gemini-api-key-here` dans `.env.example`.

### 2.3 `providers/groq_provider.py` — Groq + Llama 3.3 (gratuit)

Implémenter `GroqProvider` avec :
- Dépendance : `groq>=0.9` (à ajouter dans `requirements.txt`)
- Clé API lue depuis `GROQ_API_KEY` dans `.env`
- Modèle : `llama-3.3-70b-versatile` (~14 000 req/jour gratuit)
- Même interface que `GeminiProvider` : méthode `generate(event: Dict) -> str`
- Même prompt contextuel que Gemini
- Même gestion d'erreur avec fallback stub

Appel Groq :
```python
from groq import Groq
client = Groq(api_key=os.getenv('GROQ_API_KEY'))
response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=150,
    temperature=0.8
)
return response.choices[0].message.content.strip()
```

Ajouter `GROQ_API_KEY=your-groq-api-key-here` dans `.env.example`.

### 2.4 Mettre à jour `requirements.txt`

```
pyyaml>=6.0
python-dotenv>=1.0
requests>=2.31
google-generativeai>=0.5
groq>=0.9
```

---

## PARTIE 3 — JiraClient live avec auth HTTP

### 3.1 Implémenter les méthodes live dans `jira_client.py`

Auth : Basic Auth avec email + API token (encodé en base64).
Header : `Content-Type: application/json`, `Accept: application/json`.

```python
import base64
import requests

# Dans __init__
credentials = base64.b64encode(
    f"{self.email}:{self.api_token}".encode()
).decode()
self.auth_header = {
    "Authorization": f"Basic {credentials}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}
```

#### `add_comment(ticket_key, body)`
```
POST {base_url}/rest/api/3/issue/{ticket_key}/comment
Body: {"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph",
       "content": [{"type": "text", "text": body}]}]}}
```

#### `transition_ticket(ticket_key, new_status)`
Jira nécessite un `transition_id`, pas un nom de statut.
Implémenter une méthode privée `_get_transition_id(ticket_key, target_status) -> str | None` :
1. `GET {base_url}/rest/api/3/issue/{ticket_key}/transitions`
2. Chercher la transition dont `to.name == target_status`
3. Retourner son `id` ou `None`

```
POST {base_url}/rest/api/3/issue/{ticket_key}/transitions
Body: {"transition": {"id": transition_id}}
```

#### `assign_ticket(ticket_key, account_id)`
```
PUT {base_url}/rest/api/3/issue/{ticket_key}/assignee
Body: {"accountId": account_id}
```

#### `create_subtask(parent_key, summary, assignee_id)`
```
POST {base_url}/rest/api/3/issue
Body: {"fields": {"project": {"key": project_key}, "parent": {"key": parent_key},
       "summary": summary, "issuetype": {"name": "Sub-task"},
       "assignee": {"accountId": assignee_id}}}
```

#### `get_tickets_for_project()`
```
GET {base_url}/rest/api/3/search?jql=project={project_key} AND statusCategory != Done&maxResults=50
```
Normaliser chaque issue retournée au format du `state.json`.

### 3.2 Gestion d'erreurs HTTP — méthode privée `_handle_response`

```python
def _handle_response(self, response: requests.Response, action: str) -> dict:
    """Gère les codes HTTP et lève des exceptions explicites."""
    if response.status_code in (200, 201, 204):
        return response.json() if response.content else {}
    elif response.status_code == 401:
        logger.error("Auth invalide — vérifier JIRA_EMAIL / JIRA_API_TOKEN")
        raise PermissionError("Jira 401 Unauthorized")
    elif response.status_code == 403:
        logger.error("Permission refusée sur %s", action)
        raise PermissionError("Jira 403 Forbidden")
    elif response.status_code == 404:
        logger.warning("Ressource introuvable pour %s", action)
        return {}
    elif response.status_code == 429:
        logger.warning("Rate limit Jira — attente 60s puis retry")
        import time; time.sleep(60)
        return {}
    else:
        logger.error("Jira %s erreur %d: %s", action, response.status_code, response.text[:200])
        raise RuntimeError(f"Jira {response.status_code} on {action}")
```

### 3.3 Ajouter `jira_account_id` dans `config/teams.yaml`

```yaml
members:
  - id: alice_m
    display_name: "Alice Martin"
    role: lead
    availability: available
    jira_account_id: ""   # à remplir avec le vrai accountId Jira Cloud
```

Le `JiraClient` doit charger `config/teams.yaml` et construire un dict
`{member_id: jira_account_id}` pour les appels live.

---

## PARTIE 4 — `bootstrap_state.py`

Créer `bootstrap_state.py` à la racine :

```python
"""
Peuple state.json depuis les vrais tickets Jira (ou fixtures en dry-run).
Usage : python bootstrap_state.py --project PROJ
"""
import os
import argparse
import yaml
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

from jira_client import JiraClient
from state_manager import StateManager
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')


def bootstrap(project_key: str) -> None:
    """Reconstruit state.json depuis Jira ou les fixtures dry-run."""
    jira = JiraClient()
    state_mgr = StateManager()

    tickets_raw = jira.get_tickets_for_project()

    with open('config/teams.yaml', 'r', encoding='utf-8') as f:
        teams_config = yaml.safe_load(f)

    members = {}
    for team in teams_config.get('teams', []):
        for m in team.get('members', []):
            members[m['id']] = {
                'availability': m.get('availability', 'available'),
                'current_tickets': [],
                'team_id': team['id']
            }

    tickets = {}
    for t in tickets_raw:
        tickets[t['key']] = t

    state = {
        'last_run': None,
        'members': members,
        'tickets': tickets
    }
    state_mgr.save(state)
    logger.info('Bootstrap terminé — %d tickets, %d membres', len(tickets), len(members))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bootstrap state depuis Jira')
    parser.add_argument('--project', default=os.getenv('JIRA_PROJECT_KEY', 'PROJ'))
    args = parser.parse_args()
    bootstrap(args.project)
```

---

## PARTIE 5 — Tests à ajouter

### `tests/test_ai_writer.py`
- `test_aiwriter_uses_stub_by_default` : sans variable env, le provider est stub
- `test_aiwriter_unknown_provider_fallback` : provider inconnu → fallback stub
- `test_aiwriter_generates_string` : generate_content retourne un str non vide

### `tests/test_jira_client_dry_run.py`
- `test_add_comment_dry_run` : retourne dict avec `status: dry-run`
- `test_transition_dry_run` : retourne le bon format
- `test_live_raises_not_implemented` : avec `DRY_RUN=false`, les méthodes lèvent `NotImplementedError`

### `tests/test_providers.py`
- `test_stub_provider_covers_all_types` : s'assurer qu'il passe toujours
- `test_gemini_provider_interface` : la classe existe et a la méthode `generate`
- `test_groq_provider_interface` : idem

---

## PARTIE 6 — `.env.example` mis à jour

```env
# Provider IA : stub | gemini | groq
AI_PROVIDER=stub

# Gemini (gratuit - 1500 req/jour)
# Clé sur : https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your-gemini-api-key-here

# Groq (gratuit - ~14000 req/jour)
# Clé sur : https://console.groq.com
GROQ_API_KEY=your-groq-api-key-here

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

---

## Règles de code (identiques à phase 1)

- Python 3.11+, type hints, docstrings en français
- `logging` uniquement (pas de `print` sauf dry-run display)
- `load_dotenv()` en première instruction de tout point d'entrée
- Chemins avec `pathlib.Path`
- Erreurs HTTP catchées et loggées, n'interrompent pas le run sauf 401/403

---

## Validation finale

```bash
# Corrections actives — .env lu correctement
python main.py --events 5

# Override CLI
python main.py --events 3 --dry-run

# Bootstrap
python bootstrap_state.py --project PROJ

# Tests complets
python -m pytest -v
# Attendu : tous les tests passent dont test_ai_writer et test_jira_client_dry_run
```

## Ordre d'exécution recommandé

1. Partie 1 — 5 corrections → tester avec `python main.py --events 3`
2. `base_provider.py` + mise à jour `StubProvider`
3. `gemini_provider.py`
4. `groq_provider.py`
5. `requirements.txt` mis à jour → `pip install -r requirements.txt`
6. `jira_client.py` live (méthodes HTTP + `_handle_response`)
7. `bootstrap_state.py`
8. Nouveaux tests
9. `.env.example` + `README.md`
10. `python -m pytest -v` + `python main.py --events 5`
