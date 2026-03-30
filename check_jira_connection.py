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

credentials = base64.b64encode(
    f"{email}:{api_token}".encode('utf-8')
).decode('utf-8')
headers = {
    "Authorization": f"Basic {credentials}",
    "Accept": "application/json"
}

all_ok = True

# Check 1 : Authentification (GET /myself)
try:
    r = requests.get(
        f"{base_url}/rest/api/3/myself",
        headers=headers, timeout=10
    )
    if r.status_code == 200:
        data = r.json()
        print(f"[OK] Authentification — connecté en tant que "
              f"{data.get('displayName', '?')} "
              f"({data.get('emailAddress', '?')})")
    else:
        print(f"[ERREUR] Authentification — HTTP {r.status_code}: {r.text[:120]}")
        all_ok = False
except Exception as e:
    print(f"[ERREUR] Authentification — {e}")
    all_ok = False

# Check 2 : Projet (GET /project/{key})
try:
    r = requests.get(
        f"{base_url}/rest/api/3/project/{project_key}",
        headers=headers, timeout=10
    )
    if r.status_code == 200:
        data = r.json()
        print(f"[OK] Projet — {data.get('name', '?')} ({project_key})")
    else:
        print(f"[ERREUR] Projet — HTTP {r.status_code}: {r.text[:120]}")
        all_ok = False
except Exception as e:
    print(f"[ERREUR] Projet — {e}")
    all_ok = False

# Check 3 : Tickets ouverts — POST /search/jql (nouvel endpoint Atlassian)
try:
    r = requests.post(
        f"{base_url}/rest/api/3/search/jql",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "jql": f"project = {project_key} ORDER BY updated DESC",
            "maxResults": 50,
            "fields": ["summary", "status", "assignee"]
        },
        timeout=10
    )
    if r.status_code == 200:
        data = r.json()
        issues = data.get('issues', [])
        total = len(issues)
        print(f"[OK] Tickets ouverts (JQL) — {total} ticket(s) ouvert(s)")
        if total > 0:
            for issue in issues[:5]:
                fields = issue.get('fields', {})
                print(f"     - {issue['key']}: {fields.get('summary', '?')} "
                      f"({fields.get('status', {}).get('name', '?')})")
        else:
            print("     (projet vide ou tous les tickets sont Done — "
                  "créer des tickets avant le bootstrap)")
    else:
        print(f"[ERREUR] Tickets ouverts — HTTP {r.status_code}: {r.text[:120]}")
        all_ok = False
except Exception as e:
    print(f"[ERREUR] Tickets ouverts — {e}")
    all_ok = False

# Check 4 : Ticket spécifique KAN-9
try:
    r = requests.get(
        f"{base_url}/rest/api/3/issue/KAN-9",
        headers=headers, timeout=10
    )
    if r.status_code == 200:
        data = r.json()
        fields = data.get('fields', {})
        print(f"[OK] Ticket KAN-9 — {fields.get('summary', '?')} "
              f"({fields.get('status', {}).get('name', '?')})")
    else:
        print(f"[ERREUR] Ticket KAN-9 — HTTP {r.status_code}: {r.text[:120]}")
        all_ok = False
except Exception as e:
    print(f"[ERREUR] Ticket KAN-9 — {e}")
    all_ok = False

print()
if all_ok:
    print("Connexion Jira validée — tu peux lancer bootstrap_state.py")
else:
    print("Corriger les erreurs ci-dessus avant de continuer")
