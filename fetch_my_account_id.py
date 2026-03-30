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
