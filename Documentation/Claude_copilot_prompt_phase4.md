# Prompt GitHub Copilot — Phase 4 : Premier run Jira live
# Jira Activity Simulator — Suite de la phase 3

---

## Contexte et état actuel

- Phases 1, 2, 3 terminées — 11 tests passent, dry-run validé
- `check_jira_connection.py` retourne 3 [OK], 15 tickets ouverts détectés
- `config/teams.yaml` contient des membres fictifs (alice_m, bob_d…)
  avec `jira_account_id` vides — les vrais accountId Jira ne sont pas encore remplis
- Provider IA : stub uniquement pour cette phase
- Objectif : exécuter un premier run live sur Jira Cloud en mode sécurisé,
  en gérant proprement l'absence de vrais accountId

---

## PARTIE 1 — Récupérer et injecter les vrais accountId

### 1.1 Lancer fetch_account_ids.py et lire sa sortie

```bash
python fetch_account_ids.py
```

Ce script affiche les accountId Jira de chaque membre fictif s'il les trouve
par recherche de nom. Selon le résultat, deux cas :

**Cas A — des membres réels sont trouvés** : mettre à jour `config/teams.yaml`
en remplissant les champs `jira_account_id` correspondants.

**Cas B — aucun membre trouvé** (membres fictifs inexistants dans Jira) :
c'est le cas probable ici. Appliquer la procédure 1.2 ci-dessous.

### 1.2 Récupérer l'accountId du compte connecté (fallback sécurisé)

Créer le script `fetch_my_account_id.py` à la racine :

```python
"""
Affiche l'accountId du compte actuellement connecté à Jira.
Utilisé pour tester assign_ticket avec un vrai accountId valide.
Usage : python fetch_my_account_id.py
"""
import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

base_url  = os.getenv('JIRA_BASE_URL', '').rstrip('/')
email     = os.getenv('JIRA_EMAIL', '')
api_token = os.getenv('JIRA_API_TOKEN', '')

creds = base64.b64encode(f"{email}:{api_token}".encode()).decode()
headers = {"Authorization": f"Basic {creds}", "Accept": "application/json"}

r = requests.get(f"{base_url}/rest/api/3/myself", headers=headers, timeout=10)
data = r.json()
print(f"displayName : {data.get('displayName')}")
print(f"emailAddress: {data.get('emailAddress')}")
print(f"accountId   : {data.get('accountId')}")
print()
print("Copie cet accountId dans config/teams.yaml pour au moins un membre.")
```

Lancer ce script et copier l'`accountId` retourné dans `config/teams.yaml`
pour **au moins un membre** (par exemple `alice_m`) :

```yaml
- id: alice_m
  display_name: "Alice Martin"
  role: lead
  availability: available
  jira_account_id: "COLLER_ICI_LE_VRAI_ACCOUNT_ID"
```

Les autres membres peuvent garder `jira_account_id: ""` pour l'instant —
le simulateur gérera les assignees vides en phase live.

### 1.3 Sécuriser `assign_ticket` pour les accountId vides

Dans `jira_client.py`, modifier `assign_ticket` pour ignorer l'action si
`resolved_id` est vide plutôt que d'envoyer une requête invalide :

```python
def assign_ticket(self, ticket_key: str, account_id: str) -> dict:
    """Réassigne le ticket. Ignore silencieusement si accountId inconnu."""
    resolved_id = self._account_id_map.get(account_id, account_id)

    if self.dry_run:
        return self._dry_log('change_assignee', ticket_key,
                             f'assign to {account_id} (accountId: {resolved_id})')

    if not resolved_id or resolved_id == account_id:
        # account_id non résolu — membre fictif sans accountId Jira réel
        logger.warning(
            "assign_ticket ignoré pour %s — accountId non résolu pour '%s'. "
            "Remplir jira_account_id dans config/teams.yaml.",
            ticket_key, account_id
        )
        return {'status': 'skipped', 'reason': 'unresolved_account_id'}

    url = f"{self.base_url}/rest/api/3/issue/{ticket_key}/assignee"
    r = requests.put(
        url,
        headers=self._get_auth_headers(),
        json={"accountId": resolved_id},
        timeout=15
    )
    return self._handle_response(r, f"assign_ticket({ticket_key})")
```

---

## PARTIE 2 — Bootstrap depuis Jira réel

### 2.1 Lancer bootstrap_state.py en mode live

```bash
python bootstrap_state.py --project TON_PROJECT_KEY
```

Ce script remplace `state.json` par les vrais tickets Jira. Vérifier après
l'exécution que `state.json` contient bien les tickets récupérés.

### 2.2 Adapter le champ `team_id` dans bootstrap

**Problème identifié** : `get_tickets_for_project` remplit `team_id` avec
`self.project_key.lower()` (ex: `"proj"`), mais les équipes dans `teams.yaml`
s'appellent `"phoenix"` et `"nebula"`. Le `ScenarioEngine` ne trouvera aucun
ticket correspondant à ces équipes.

**Correction** dans `bootstrap_state.py`, après la récupération des tickets :

```python
# Récupérer le premier team_id disponible dans teams.yaml comme valeur par défaut
default_team_id = teams_config.get('teams', [{}])[0].get('id', 'phoenix')

tickets: dict = {}
for t in tickets_raw:
    # Remplacer team_id généré par le vrai team_id de la config
    t['team_id'] = default_team_id
    tickets[t['key']] = t
```

Et dans `jira_client.py`, mettre à jour `get_tickets_for_project` pour ne plus
mettre `team_id` dans les tickets retournés — laisser `bootstrap_state.py`
l'assigner depuis la config :

```python
tickets.append({
    'key': issue['key'],
    'summary': fields.get('summary', ''),
    'status': fields.get('status', {}).get('name', 'To Do'),
    'assignee_id': assignee.get('accountId', ''),
    # 'team_id' retiré — assigné par bootstrap_state.py
    'is_blocked': False
})
```

### 2.3 Vérifier state.json après bootstrap

Après `python bootstrap_state.py --project TON_PROJECT_KEY`, ouvrir
`state.json` et vérifier :
- Les tickets ont `team_id` égal à `"phoenix"` (ou le premier team_id)
- Les membres sont présents avec `availability: available`
- `last_run` est `null`

---

## PARTIE 3 — Premier run live sécurisé

### 3.1 Configuration `.env` pour le run live

Dans `.env`, mettre exactement :
```env
AI_PROVIDER=stub
DRY_RUN=false
```
Garder `DRY_RUN=true` en commentaire pour pouvoir revenir facilement :
```env
# DRY_RUN=true   ← remettre cette ligne pour revenir en dry-run
DRY_RUN=false
```

### 3.2 Limiter le premier run à 2 événements

Pour le premier test live, utiliser seulement 2 événements et uniquement
les types les plus sûrs (commentaire et changement de statut) :

Modifier temporairement `config/scenarios.yaml` pour ne garder que
2 types actifs lors du premier test :

```yaml
scenarios:
  - id: add_comment
    type: add_comment
    weight: 70
    description: "Un membre de l'équipe ajoute un commentaire de suivi"

  - id: change_status
    type: change_status
    weight: 30
    description: "Un ticket avance dans le workflow"

  # Les autres scénarios commentés pour le premier test live
  # - id: change_assignee ...
  # - id: block_ticket ...
  # - id: set_absence ...
  # - id: return_from_absence ...
  # - id: add_subtask ...
```

Cela évite les problèmes de `assign_ticket` avec des accountId vides et les
modifications de `is_blocked` tant que les vrais accountId ne sont pas remplis.

### 3.3 Lancer le premier run live

```bash
python main.py --events 2
```

Sortie attendue (sans `--dry-run`, `DRY_RUN=false` dans `.env`) :

```
[INFO] AIWriter: using provider 'stub'
[INFO] JiraClient: DRY_RUN=False — HTTP calls ACTIVE
[INFO] Run started — 2 events requested
[INFO] Scenario choisi : add_comment
[INFO] add_comment on PROJ-X → HTTP 201 Created
[INFO] Scenario choisi : change_status
[INFO] change_status on PROJ-Y → transition to 'In Review'
[INFO] Run complete — 2 events executed, 0 skipped
[INFO] State saved to state.json
```

Vérifier immédiatement dans Jira Cloud que :
- Un commentaire a bien été posté sur le ticket concerné
- Le statut d'un ticket a bien changé

### 3.4 Restaurer les scénarios complets après validation

Une fois les 2 premiers événements validés dans Jira, restaurer
`config/scenarios.yaml` avec tous les scénarios (décommenter les lignes).

---

## PARTIE 4 — Gestion des erreurs live à surveiller

### 4.1 Ajouter un log explicite au démarrage live dans `jira_client.py`

Modifier le message de log au démarrage pour qu'il soit plus visible
en mode live :

```python
if self.dry_run:
    logger.info("JiraClient: DRY_RUN=True — aucun appel HTTP vers Jira")
else:
    logger.warning(
        "JiraClient: MODE LIVE ACTIF — les appels HTTP vers Jira sont réels !"
    )
```

### 4.2 Ajouter un test de non-régression pour `assign_ticket` avec accountId vide

Dans `tests/test_jira_client_dry_run.py`, ajouter :

```python
def test_assign_ticket_skips_unresolved_account_id(monkeypatch):
    """assign_ticket doit ignorer silencieusement un accountId non résolu."""
    monkeypatch.setenv('DRY_RUN', 'false')
    monkeypatch.setenv('JIRA_BASE_URL', 'https://fake.atlassian.net')
    monkeypatch.setenv('JIRA_EMAIL', 'test@test.com')
    monkeypatch.setenv('JIRA_API_TOKEN', 'fake_token')
    client = JiraClient(force_dry_run=False)
    # member_id non résolu (pas dans _account_id_map)
    result = client.assign_ticket('PROJ-1', 'membre_fictif')
    assert result.get('status') == 'skipped'
    assert result.get('reason') == 'unresolved_account_id'
```

---

## PARTIE 5 — Tests de non-régression

Après toutes les modifications, vérifier que les tests passent :

```bash
python -m pytest -v
# Attendu : 12+ tests passent
```

---

## Ordre d'exécution pour Copilot

1. Créer `fetch_my_account_id.py` (Partie 1.2)
2. Corriger `assign_ticket` dans `jira_client.py` (Partie 1.3)
3. Corriger `bootstrap_state.py` pour le `team_id` (Partie 2.2)
4. Corriger `get_tickets_for_project` dans `jira_client.py` (Partie 2.2)
5. Ajouter le log WARNING en mode live dans `jira_client.py` (Partie 4.1)
6. Ajouter le test `test_assign_ticket_skips_unresolved_account_id` (Partie 4.2)
7. Lancer `python -m pytest -v` → tous les tests doivent passer
8. Lancer `python fetch_my_account_id.py` et copier l'accountId dans teams.yaml
9. Lancer `python bootstrap_state.py --project TON_PROJECT_KEY`
10. Modifier `config/scenarios.yaml` pour ne garder que add_comment et change_status
11. Mettre `DRY_RUN=false` dans `.env`
12. Lancer `python main.py --events 2` et vérifier dans Jira Cloud

---

## Règles

- Ne pas modifier scheduler.py, main.py, scenario_engine.py, ai_writer.py
- Ne pas changer AI_PROVIDER — garder stub
- Conserver tous les timeouts à 15s
- `load_dotenv()` reste en première instruction de tout point d'entrée
- En cas d'erreur HTTP inattendue lors du run live, remettre DRY_RUN=true
  immédiatement et analyser les logs avant de relancer
