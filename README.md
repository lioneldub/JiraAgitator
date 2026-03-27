# Jira Activity Simulator

Simulateur d'activité Jira Cloud pour équipes Scrum (phase 1).
Génère des événements de type changement de statut, commentaires, réassignations, blocages, absences.
Architecture modulaire, stub IA et mode dry-run.

## Prérequis

- Python 3.11+

## Installation

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

## Configuration

Copiez `.env.example` en `.env` et remplissez les valeurs.

## Lancement

```bash
python main.py --events 5
```

## Variables d'environnement

| Variable | Description | Exemple |
|---|---|---|
| AI_PROVIDER | Provider IA (`stub`/`gemini`/`groq`) | stub |
| JIRA_BASE_URL | URL Jira Cloud | https://your-domain.atlassian.net |
| JIRA_EMAIL | Email Jira | your-email@example.com |
| JIRA_API_TOKEN | Jeton API Jira | your-api-token-here |
| JIRA_PROJECT_KEY | Clé projet Jira | PROJ |
| DRY_RUN | Mode dry-run `true`/`false` | true |
| EVENTS_PER_RUN | Nombre d'événements par run | 3 |

## Modes

- `stub`: génération locale, pas d'IA réelle.
- IA réelle: à implémenter via provider externe.
- `dry-run`: aucune requête HTTP Jira, simulation seule.
- `live`: exécuter les vrais appels Jira (TODO).
