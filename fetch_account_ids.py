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

if not all([base_url, email, api_token]):
    print("[ERREUR] JIRA_BASE_URL, JIRA_EMAIL ou JIRA_API_TOKEN manquant dans .env")
    exit(1)

credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}

teams_path = Path('config/teams.yaml')
if not teams_path.exists():
    print(f"[ERREUR] {teams_path} non trouvé")
    exit(1)

with teams_path.open('r', encoding='utf-8') as f:
    teams_cfg = yaml.safe_load(f)

print("Recherche des accountId Jira pour chaque membre :\n")
for team in teams_cfg.get('teams', []):
    print(f"  Équipe : {team['name']}")
    for member in team.get('members', []):
        name = member['display_name']
        try:
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
        except Exception as e:
            print(f"    {name} → erreur: {e}")
    print()

print("Copie les accountId dans config/teams.yaml sous le champ jira_account_id.")
