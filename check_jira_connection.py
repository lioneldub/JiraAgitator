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

credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
headers = {
    "Authorization": f"Basic {credentials}",
    "Accept": "application/json"
}

checks = [
    ("Authentification",      f"{base_url}/rest/api/3/myself"),
    ("Projet",                f"{base_url}/rest/api/3/project/{project_key}"),
    ("Tickets ouverts (JQL)", f"{base_url}/rest/api/3/search?jql=project={project_key}+AND+statusCategory!=Done&maxResults=5"),
]

all_ok = True
for label, url in checks:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if label == "Authentification":
                print(f"[OK] {label} — connecté en tant que {data.get('displayName', '?')}")
            elif label == "Projet":
                print(f"[OK] {label} — {data.get('name','?')} ({project_key})")
            else:
                total = data.get('total', 0)
                print(f"[OK] {label} — {total} ticket(s) ouvert(s)")
        else:
            print(f"[ERREUR] {label} — HTTP {r.status_code}: {r.text[:120]}")
            all_ok = False
    except Exception as e:
        print(f"[ERREUR] {label} — {e}")
        all_ok = False

print()
if all_ok:
    print("Connexion Jira validée — tu peux passer DRY_RUN=false dans .env")
else:
    print("Corriger les erreurs ci-dessus avant de passer en mode live")
