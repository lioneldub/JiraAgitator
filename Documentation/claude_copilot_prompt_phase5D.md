# Prompt GitHub Copilot — Phase 5D : Provider IA Gemini + 8 nouveaux scénarios
# Jira Activity Simulator — Commentaires contextuels + enrichissement scénarios

---

## Contexte et état actuel

- Phases 5A/5B/5C terminées — 22 scénarios actifs, backlog auto-équilibré
- Provider IA : stub fonctionnel, Gemini et Groq squelettés mais jamais testés en vrai
- Objectif : brancher Gemini comme provider IA par défaut, enrichir les prompts
  avec le contexte complet (statuts before/after, membres, Epic), ajouter
  les 8 scénarios Gemini, et implémenter la logique de commentaires sur transitions

---

## PARTIE 1 — Réécriture complète de `providers/gemini_provider.py`

### 1.1 Prompts contextuels par type de scénario

Remplacer intégralement `providers/gemini_provider.py` par la version
avec des prompts spécialisés par scénario :

```python
"""
Provider IA Gemini — génération de contenu contextuel pour le simulateur Jira.
Utilise Gemini 2.0 Flash (tier gratuit : 1500 req/jour).
"""
import os
import logging
import random
from typing import Dict
from dotenv import load_dotenv

load_dotenv()

from providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

# Fallback si l'API échoue
FALLBACK_RESPONSES = {
    'add_comment': [
        "Point de suivi : avancement conforme aux attentes, je continue sur cette direction.",
        "Quelques points bloquants identifiés, je reviens avec une proposition.",
        "RAS de mon côté, en attente de retour avant de continuer.",
    ],
    'change_status': [
        "Passage de statut effectué suite à l'avancement du ticket.",
        "Transition validée après vérification des critères d'acceptance.",
    ],
    'create_issue': [
        "Nouveau ticket créé suite à une anomalie détectée.",
        "Création d'une tâche complémentaire identifiée lors de l'analyse.",
    ],
    'default': ["Action effectuée conformément au processus de l'équipe."],
}


class GeminiProvider(BaseProvider):
    """Provider Gemini 2.0 Flash pour la génération de contenu simulé."""

    MODEL = "gemini-2.0-flash"

    def __init__(self) -> None:
        try:
            import google.generativeai as genai
            api_key = os.getenv('GEMINI_API_KEY', '')
            if not api_key:
                raise ValueError("GEMINI_API_KEY manquant dans .env")
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(self.MODEL)
            logger.info("GeminiProvider initialisé avec le modèle %s", self.MODEL)
        except Exception as e:
            logger.error("GeminiProvider : échec d'initialisation — %s", e)
            self._model = None

    def generate(self, event: Dict) -> str:
        """Génère un texte contextuel pour l'événement via Gemini."""
        if self._model is None:
            return self._fallback(event)
        try:
            prompt = self._build_prompt(event)
            response = self._model.generate_content(prompt)
            text = response.text.strip()
            logger.debug("Gemini → %s caractères générés", len(text))
            return text
        except Exception as e:
            logger.warning("Gemini erreur API : %s — utilisation du fallback", e)
            return self._fallback(event)

    def _build_prompt(self, event: Dict) -> str:
        """Construit le prompt contextuel selon le type de scénario."""
        scenario_id  = event.get('scenario_id', '')
        member_name  = event.get('member_name', 'Un membre')
        member_role  = event.get('member_role', 'dev')
        team_id      = event.get('team_id', "l'équipe")
        ticket_key   = event.get('ticket_key', '')
        ticket_sum   = event.get('ticket_summary', '')
        issue_type   = event.get('issue_type', 'Story')
        ctx          = event.get('context', {})
        status_from  = ctx.get('current_status', '')
        status_to    = ctx.get('target_status', '')
        epic_summary = ctx.get('epic_summary', '')
        target_member = ctx.get('target_member_name', '')
        priority     = ctx.get('priority', 'Medium')

        # Contexte commun injecté dans tous les prompts
        base_context = f"""Tu simules {member_name}, {member_role} dans l'équipe "{team_id}".
Ticket concerné : {ticket_key} [{issue_type}] — "{ticket_sum}"
Priorité : {priority}{f' | Epic : "{epic_summary}"' if epic_summary else ''}

RÈGLES ABSOLUES :
- Maximum 3 phrases. Naturel et professionnel, jamais corporate.
- En français. Varie les formulations — évite de commencer par "Je".
- Réponds UNIQUEMENT avec le message, sans introduction, sans guillemets, sans signature.
"""

        # Prompts spécialisés par scénario
        prompts = {
            'mise_a_jour_progression': base_context + """
Action : tu postes une mise à jour de progression sur ce ticket.
Mentionne où tu en es concrètement (ce qui est fait, ce qui reste, un éventuel point d'attention).
""",
            'synthese_epic': base_context + """
Action : tu commentes cette Epic en tant que Lead pour faire un point de suivi.
Parle de la progression globale, d'un risque identifié ou d'une décision à prendre.
""",
            'precision_qa': base_context + f"""
Action : tu es QA et tu laisses un commentaire de revue sur ce ticket ({status_from}).
Mentionne un point de test, une anomalie, ou une validation effectuée.
""",
            'blocage': base_context + f"""
Action : tu passes ce ticket en BLOCKED et tu expliques le blocage.
Sois précis sur la cause (dépendance externe, specs floues, problème technique).
Mentionne ce qui est nécessaire pour débloquer.
""",
            'rejet_review': base_context + f"""
Action : tu retournes ce ticket de IN REVIEW vers IN PROGRESS après ta revue.
Explique brièvement ce qui n'est pas satisfaisant (test manquant, cas non couvert, etc.).
""",
            'demande_clarification_metier': base_context + f"""
Action : tu es DEV et tu interpelles {target_member or 'le BA'} pour une clarification métier.
Pose une question technique précise sur ce ticket — spécifications, comportement attendu, règle de gestion.
""",
            'affinement_backlog': base_context + f"""
Action : tu affines ce ticket lors d'une session de backlog grooming.
Ajoute une précision sur les critères d'acceptance, une contrainte technique, ou une dépendance.
""",
            'relance_lead': base_context + f"""
Action : tu es Lead et ce ticket n'a pas bougé depuis plusieurs jours.
Laisse un message de relance courtois mais direct — demande un point de situation.
""",
            'fragmentation_story': base_context + f"""
Action : tu fragmente cette Story trop complexe en deux parties.
Explique pourquoi la story est trop grande et décris les deux nouvelles sous-parties.
""",
            'cloture_epic': base_context + f"""
Action : tu passes cette Epic en DONE après finalisation des travaux.
Fais un court bilan : ce qui a été livré, les points notables, les enseignements.
""",
            'pret_mise_en_service': base_context + f"""
Action : tu valides et passes ces tickets en DONE avant une mise en service.
Confirme que les validations sont faites et que les tickets sont prêts pour le déploiement.
""",
            'lien_transverse_inter_equipes': base_context + f"""
Action : tu crées un lien "Relates to" entre ce ticket et un ticket d'une autre équipe.
Explique en une phrase pourquoi ces deux tickets sont liés.
""",
        }

        # Prompt pour les transitions avec commentaire optionnel
        if event.get('context', {}).get('transition_comment') and status_from and status_to:
            return base_context + f"""
Action : ce ticket passe de "{status_from}" à "{status_to}".
Laisse un commentaire naturel qui explique ou accompagne ce changement de statut.
"""

        return prompts.get(scenario_id,
               prompts.get(event.get('type', ''), base_context + """
Action : effectue l'action sur ce ticket et laisse un commentaire approprié.
"""))

    def _describe_event_type(self, event_type: str) -> str:
        """Description textuelle d'un type d'événement (utilisé dans certains prompts)."""
        descriptions = {
            'add_comment':    'Commentaire de suivi',
            'change_status':  'Changement de statut',
            'change_assignee':'Réassignation',
            'create_issue':   'Création de ticket',
            'create_subtask': 'Création de sous-tâche',
            'create_link':    'Création de lien',
            'update_field':   'Mise à jour de champ',
            'split_issue':    'Fragmentation de ticket',
        }
        return descriptions.get(event_type, 'Action')

    def _fallback(self, event: Dict) -> str:
        """Retourne une réponse de fallback si Gemini est indisponible."""
        event_type = event.get('type', 'default')
        responses = FALLBACK_RESPONSES.get(event_type,
                    FALLBACK_RESPONSES['default'])
        return random.choice(responses)
```

### 1.2 Même réécriture pour `providers/groq_provider.py`

Appliquer la même structure de prompts à `groq_provider.py` —
même `_build_prompt`, même fallback, même structure.
Seul l'appel API change (utiliser le client Groq avec `llama-3.3-70b-versatile`).

---

## PARTIE 2 — Commentaires optionnels sur les transitions de statut

### 2.1 Nouvelle variable d'environnement

Ajouter dans `.env.example` :
```env
# Probabilité d'ajouter un commentaire IA lors d'un changement de statut (0.0 à 1.0)
# BLOCKED : toujours 1.0 (ignoré pour ce statut)
COMMENT_ON_TRANSITION=0.30
```

### 2.2 Logique dans `scheduler.py` — branche `change_status`

Modifier la branche `change_status` pour ajouter un commentaire avec probabilité
configurable, et TOUJOURS pour BLOCKED avec parfois un lien "blocked by" :

```python
elif stype == 'change_status':
    target = event['context'].get('target_status', '')

    # Exécuter la transition
    jira_client.transition_ticket(key, target)
    state_manager.sync_ticket_after_event(key, {'status': target})

    comment_prob = float(os.getenv('COMMENT_ON_TRANSITION', '0.30'))
    add_comment  = False
    is_blocking  = target.upper() == 'BLOCKED'

    if is_blocking:
        # BLOCKED : commentaire obligatoire
        add_comment = True
    elif random.random() < comment_prob:
        # Autres transitions : commentaire probabiliste
        add_comment = True

    if add_comment:
        # Enrichir l'event avec le contexte de transition pour le prompt IA
        event['context']['transition_comment'] = True
        event['context']['status_destination'] = target
        comment_text = ai_writer.generate_content(event)
        jira_client.add_comment(key, comment_text)
        logger.info(
            "[COMMENT] Commentaire ajouté sur %s (%s → %s)",
            key, event['context'].get('current_status', '?'), target
        )

    # BLOCKED : parfois ajouter un lien "blocked by" (30% de chance)
    if is_blocking and random.random() < 0.30:
        # Chercher un ticket candidat bloquant dans le même projet
        project_prefix = key.split('-')[0]
        candidates_blocking = [
            t['key'] for t in state.get('tickets', {}).values()
            if t['key'] != key
            and t['key'].startswith(project_prefix)
            and t.get('status_category') != 'DONE'
            and t.get('issue_type') in ('Bug', 'Story', 'Task')
        ]
        if candidates_blocking:
            blocking_key = random.choice(candidates_blocking)
            jira_client.create_issue_link(key, blocking_key, 'is blocked by')
            state_manager.add_issue_link(key, blocking_key, 'is blocked by')
            logger.info(
                "[LINK] %s is blocked by %s (ajout automatique)",
                key, blocking_key
            )
```

### 2.3 Enrichir le contexte de l'event avec l'Epic summary

Dans `scenario_engine.build_event()`, ajouter l'`epic_summary` dans le context
pour que les prompts IA puissent la mentionner :

```python
# Dans build_event, lors de la construction du context :
epic_key = ticket.get('epic_key')
epic_summary = ''
if epic_key:
    epic_ticket = state.get('tickets', {}).get(epic_key, {})
    epic_summary = epic_ticket.get('summary', '')

# Dans le dict context :
'epic_summary': epic_summary,
```

---

## PARTIE 3 — 8 nouveaux scénarios dans `config/scenarios.yaml`

Ajouter à la suite des scénarios existants :

```yaml
  # --- Phase 5D — Scénarios de cohérence produit et collaboration ---

  - id: demande_clarification_metier
    type: add_comment
    weight: 12
    description: "Un DEV demande des précisions au BA sur une Story en IN PROGRESS"
    constraints:
      issue_types: ["Story", "Feature"]
      statuses: ["IN PROGRESS"]
      actor_roles: ["DEV"]
      target_actor_roles: ["BA"]

  - id: fragmentation_story
    type: split_issue
    weight: 3
    description: "Une Story trop complexe est divisée en deux nouvelles Stories"
    constraints:
      issue_types: ["Story"]
      statuses: ["IN PROGRESS"]
      actor_roles: ["lead", "BA"]
      new_issue_initial_status: "TO DO"

  - id: propagation_epic_progress
    type: change_status
    weight: 6
    description: "L'Epic passe en IN PROGRESS (déclenché par une Story enfant)"
    constraints:
      issue_types: ["Epic"]
      statuses: ["TO DO", "IDEA"]
      target_status: "IN PROGRESS"
      actor_roles: ["lead", "BA", "DEV"]
      guard: "random_80_percent"

  - id: lien_transverse_inter_equipes
    type: create_link
    weight: 4
    description: "Lien 'Relates to' entre un ticket d'un projet et un autre projet"
    constraints:
      issue_types: ["Story", "Feature", "Bug"]
      statuses: ["TO DO", "IN PROGRESS"]
      actor_roles: ["lead", "BA"]
      link_type: "relates to"
      cross_project: true

  - id: tache_hors_epic_erreur
    type: create_issue
    weight: 4
    description: "Création d'une Task isolée sans Epic (erreur humaine ou Run pur)"
    constraints:
      actor_roles: ["DEV", "BA"]
      issue_type_to_create: "Task"
      initial_status: "TO DO"
      requires_epic: false

  - id: etiquetage_version
    type: update_field
    weight: 7
    description: "Ajout de labels de version ou de domaine sur un ticket"
    constraints:
      issue_types: ["Story", "Bug", "Feature"]
      statuses: ["IN PROGRESS", "IN REVIEW"]
      actor_roles: ["lead", "QA", "BA"]
      field_to_update: "labels"

  - id: cloture_epic
    type: change_status
    weight: 2
    description: "Passage d'une Epic à DONE quand la majorité des enfants sont terminés"
    constraints:
      issue_types: ["Epic"]
      statuses: ["IN PROGRESS"]
      target_status: "DONE"
      actor_roles: ["BA", "lead"]
      guard: "epic_majority_done"

  - id: pret_mise_en_service
    type: change_status
    weight: 4
    description: "Passage de plusieurs tickets IN REVIEW vers DONE (fin de batch)"
    constraints:
      issue_types: ["Story", "Bug", "Feature"]
      statuses: ["IN REVIEW"]
      target_status: "DONE"
      actor_roles: ["QA", "lead"]
      is_bulk: true
      bulk_max: 4
```

---

## PARTIE 4 — Nouveaux types et guards dans `scenario_engine.py` et `scheduler.py`

### 4.1 Guard `random_80_percent`

```python
# Dans build_event, après les autres guards :
if guard == 'random_80_percent':
    if random.random() > 0.80:
        continue   # 20% de chance de skipper ce candidat
```

### 4.2 Guard `epic_majority_done`

```python
if guard == 'epic_majority_done':
    epic_key = ticket['key']
    # Trouver les Stories/Bugs rattachés à cette Epic
    children = [
        t for t in state.get('tickets', {}).values()
        if t.get('epic_key') == epic_key
        and t.get('issue_type') in ('Story', 'Bug', 'Feature', 'Task')
    ]
    if not children:
        continue   # Epic sans enfants — ne pas clôturer
    done_count = sum(1 for c in children
                     if c.get('status_category') == 'DONE')
    ratio = done_count / len(children)
    if ratio < 0.70:
        continue   # Moins de 70% des enfants DONE
    logger.debug(
        "Epic %s : %d/%d enfants DONE (%.0f%%) — éligible à la clôture",
        epic_key, done_count, len(children), ratio * 100
    )
```

### 4.3 Branche `split_issue` dans `scheduler.py`

```python
elif stype == 'split_issue':
    source_key   = event['ticket_key']
    source_summ  = event.get('ticket_summary', 'Story complexe')
    epic_key     = event['context'].get('epic_key')
    project_key  = source_key.split('-')[0]
    account_id   = _resolve_account_id(event['member_id'], state_manager)

    # Générer les résumés des deux nouvelles Stories via IA
    part1_content = ai_writer.generate_content({
        **event,
        'scenario_id': 'fragmentation_story',
        'context': {**event['context'],
                    'split_part': 1, 'source_summary': source_summ}
    })
    part2_content = ai_writer.generate_content({
        **event,
        'scenario_id': 'fragmentation_story',
        'context': {**event['context'],
                    'split_part': 2, 'source_summary': source_summ}
    })

    # Créer les deux nouvelles Stories
    for part_summary in [part1_content[:100], part2_content[:100]]:
        fields = {
            'project': {'key': project_key},
            'summary': part_summary,
            'issuetype': {'name': 'Story'},
            'priority': {'name': event['context'].get('priority', 'Medium')},
            'assignee': {'accountId': account_id},
        }
        if epic_key:
            fields['parent'] = {'key': epic_key}
        jira_client.create_issue(fields)

    # Passer la Story source en CANCELLED avec commentaire
    cancel_comment = (f"Story fragmentée en deux tickets plus petits. "
                      f"Voir les nouvelles Stories créées dans ce sprint.")
    jira_client.add_comment(source_key, cancel_comment)
    jira_client.transition_ticket(source_key, 'CANCELLED')
    state_manager.sync_ticket_after_event(source_key, {'status': 'CANCELLED'})
    logger.info("[SPLIT] %s fragmenté → 2 nouvelles Stories | source CANCELLED",
                source_key)
```

### 4.4 Branche `is_bulk` — pret_mise_en_service

Dans la branche `change_status`, détecter le flag `is_bulk` avant d'exécuter :

```python
elif stype == 'change_status':
    is_bulk  = event['context'].get('is_bulk', False)
    bulk_max = event['context'].get('bulk_max', 4)
    target   = event['context'].get('target_status', '')

    if is_bulk:
        # Chercher jusqu'à bulk_max tickets supplémentaires du même statut/type
        project_prefix = key.split('-')[0]
        constraints_types = event['context'].get('allowed_types', [])
        bulk_candidates = [
            t['key'] for t in state.get('tickets', {}).values()
            if t['key'] != key
            and t['key'].startswith(project_prefix)
            and t.get('status', '').upper() == event['context'].get('current_status', '')
            and (not constraints_types or t.get('issue_type') in constraints_types)
        ][:bulk_max - 1]   # -1 car le ticket principal est déjà traité

        all_keys = [key] + bulk_candidates
        for bulk_key in all_keys:
            jira_client.transition_ticket(bulk_key, target)
            state_manager.sync_ticket_after_event(bulk_key, {'status': target})
        logger.info(
            "[BULK] %d tickets passés en %s : %s",
            len(all_keys), target, ', '.join(all_keys)
        )
        executed += 1
        continue   # Passer à l'événement suivant sans le traitement standard
    # ... traitement standard change_status ...
```

### 4.5 Sélection cross-project pour `lien_transverse_inter_equipes`

Dans la branche `create_link` de `scheduler.py`, détecter `cross_project: true`
et cibler un ticket d'un autre projet :

```python
elif stype == 'create_link':
    link_type    = event['context'].get('link_type', 'relates to')
    cross_project = event['context'].get('cross_project', False)
    from_prefix  = key.split('-')[0]

    candidates = [
        t['key'] for t in state.get('tickets', {}).values()
        if t['key'] != key
        and t.get('status_category') != 'DONE'
        and (
            # Cross-project : cibler un autre projet
            (cross_project and t['key'].split('-')[0] != from_prefix)
            or
            # Même projet si pas cross
            (not cross_project and t['key'].split('-')[0] == from_prefix)
        )
    ]
    if candidates:
        to_key = random.choice(candidates)
        jira_client.create_issue_link(key, to_key, link_type)
        state_manager.add_issue_link(key, to_key, link_type)
        logger.info("[LINK] %s '%s' %s", key, link_type, to_key)
```

### 4.6 Gestion de `target_actor_roles` dans `scenario_engine.build_event()`

Pour `demande_clarification_metier`, le champ `target_actor_roles` doit
permettre de trouver un membre cible (le BA) différent du membre acteur (le DEV) :

```python
# Dans build_event, après la sélection du member acteur :
target_roles = constraints.get('target_actor_roles', [])
target_member = None
if target_roles:
    target_candidates = [
        {'id': mid, **data}
        for mid, data in state.get('members', {}).items()
        if data.get('role', '').lower() in [r.lower() for r in target_roles]
        and data.get('availability') == 'available'
        and mid != member['id']
        and team_id in data.get('team_ids', [])
    ]
    if target_candidates:
        target_member = random.choice(target_candidates)

# Dans le dict event retourné :
'context': {
    ...
    'target_member_id': target_member['id'] if target_member else None,
    'target_member_name': target_member.get('display_name', '') if target_member else '',
    ...
}
```

### 4.7 Labels prédéfinis pour `etiquetage_version`

Dans `scheduler.py`, branche `update_field` avec `field_to_update == 'labels'` :

```python
elif field_name == 'labels':
    version_labels = ['v2026.1', 'v2026.2', 'v2026.3']
    domain_labels  = ['security', 'performance', 'ux', 'api', 'database',
                      'monitoring', 'authentication', 'migration']
    # Choisir 1 label de version (20% de chance) + 1 label de domaine
    new_labels = [random.choice(domain_labels)]
    if random.random() < 0.20:
        new_labels.append(random.choice(version_labels))
    jira_client.update_issue_field(key, 'labels', new_labels)
    state_manager.sync_ticket_after_event(key, {'labels': new_labels})
```

---

## PARTIE 5 — Mise à jour du `StubProvider` pour les nouveaux scénarios

Ajouter dans `STUB_RESPONSES` de `providers/stub_provider.py` :

```python
'demande_clarification_metier': [
    "Salut Fatou, j'ai besoin d'une précision sur le comportement attendu — "
    "est-ce qu'on doit gérer le cas où l'utilisateur n'a pas de profil complet ?",
    "Une question sur les specs : le message d'erreur doit-il être affiché "
    "en français uniquement ou aussi en anglais selon la locale ?",
    "Je bloque sur la règle de gestion pour les comptes inactifs — "
    "est-ce qu'on les exclut du scope ou on gère un cas particulier ?",
],
'fragmentation_story': [
    "Partie 1 : mise en place de la structure de base et des APIs",
    "Partie 2 : intégration UI et tests d'acceptance",
    "Partie 1 : backend et logique métier",
    "Partie 2 : frontend et validation end-to-end",
],
'propagation_epic_progress': [
    "Epic mise en IN PROGRESS suite au démarrage des premières Stories.",
    "Lancement officiel de cet Epic — premières Stories en cours.",
],
'lien_transverse_inter_equipes': [
    "Lien créé — ce ticket a une dépendance fonctionnelle avec le projet voisin.",
    "Relation identifiée lors de la session inter-équipes.",
],
'etiquetage_version': [
    "Labellisation appliquée pour faciliter le suivi et le reporting.",
],
'cloture_epic': [
    "Epic clôturée — la majorité des Stories livrées et validées. "
    "Quelques points de polish à suivre dans la prochaine itération.",
    "Fermeture de l'Epic après validation du déploiement en production.",
],
'pret_mise_en_service': [
    "Validation finale effectuée — tickets prêts pour la mise en production.",
    "Tests de non-régression OK, go pour le déploiement.",
],
'tache_hors_epic_erreur': [
    "Tâche administrative à traiter rapidement.",
    "Action Run urgente — hors périmètre sprint.",
],
```

---

## PARTIE 6 — Tests à ajouter

### `tests/test_gemini_provider.py`

```python
import pytest
from unittest.mock import MagicMock, patch


def test_gemini_provider_uses_fallback_when_no_api_key(monkeypatch):
    """Sans clé API, GeminiProvider doit utiliser le fallback stub."""
    monkeypatch.setenv('GEMINI_API_KEY', '')
    from providers.gemini_provider import GeminiProvider
    p = GeminiProvider()
    result = p.generate({'type': 'add_comment', 'scenario_id': 'mise_a_jour_progression',
                         'member_name': 'Paul', 'member_role': 'DEV',
                         'team_id': 'phoenix', 'ticket_key': 'POT-1',
                         'ticket_summary': 'Test', 'issue_type': 'Story',
                         'context': {}})
    assert isinstance(result, str)
    assert len(result) > 0


def test_gemini_provider_build_prompt_contains_member_name(monkeypatch):
    """Le prompt doit contenir le nom du membre."""
    monkeypatch.setenv('GEMINI_API_KEY', 'fake_key')
    with patch('google.generativeai.configure'), \
         patch('google.generativeai.GenerativeModel'):
        from providers.gemini_provider import GeminiProvider
        p = GeminiProvider()
        event = {
            'type': 'add_comment',
            'scenario_id': 'mise_a_jour_progression',
            'member_name': 'Paul Dupont',
            'member_role': 'DEV',
            'team_id': 'phoenix',
            'ticket_key': 'POT-5',
            'ticket_summary': 'Implémentation OAuth',
            'issue_type': 'Story',
            'context': {'current_status': 'IN PROGRESS', 'epic_summary': 'Auth Epic'}
        }
        prompt = p._build_prompt(event)
        assert 'Paul Dupont' in prompt
        assert 'POT-5' in prompt
        assert 'Auth Epic' in prompt


def test_transition_comment_prompt_includes_statuses(monkeypatch):
    """Le prompt de transition doit mentionner les statuts before/after."""
    monkeypatch.setenv('GEMINI_API_KEY', 'fake_key')
    with patch('google.generativeai.configure'), \
         patch('google.generativeai.GenerativeModel'):
        from providers.gemini_provider import GeminiProvider
        p = GeminiProvider()
        event = {
            'type': 'change_status',
            'scenario_id': 'engagement',
            'member_name': 'Pierre',
            'member_role': 'DEV',
            'team_id': 'phoenix',
            'ticket_key': 'POT-3',
            'ticket_summary': 'Migration DB',
            'issue_type': 'Story',
            'context': {
                'current_status': 'TO DO',
                'target_status': 'IN PROGRESS',
                'transition_comment': True,
                'epic_summary': ''
            }
        }
        prompt = p._build_prompt(event)
        assert 'TO DO' in prompt
        assert 'IN PROGRESS' in prompt
```

---

## Ordre d'exécution pour Copilot

1. **Partie 1** : réécrire `gemini_provider.py` et `groq_provider.py`
2. **Partie 2** : ajouter `COMMENT_ON_TRANSITION` dans `.env.example`
   + logique commentaire + lien blocked-by dans `scheduler.py`
   + `epic_summary` dans `scenario_engine.build_event()`
3. **Partie 3** : ajouter les 8 scénarios dans `config/scenarios.yaml`
4. **Partie 4** : guards + branches nouvelles dans `scenario_engine.py`
   et `scheduler.py`
5. **Partie 5** : enrichir `stub_provider.py`
6. **Partie 6** : `tests/test_gemini_provider.py`
7. `python -m pytest -v` → tous les tests doivent passer
8. **Test stub + dry-run** :
   `python main.py --events 10 --dry-run`
   → vérifier que les nouveaux scénarios apparaissent dans les logs
   → vérifier que des commentaires sont ajoutés sur les transitions
9. **Test Gemini réel** (après avoir mis `AI_PROVIDER=gemini` dans `.env`) :
   `python main.py --events 3 --dry-run`
   → vérifier que les textes générés sont cohérents et contextuels

---

## Sortie console attendue

```
[INFO] AIWriter: using provider 'gemini'
[INFO] GeminiProvider initialisé avec le modèle gemini-2.0-flash
[INFO] Run started — 10 events requested
[INFO] Scénario 'blocage' → ticket POT-12 [Bug] statut 'IN PROGRESS' assigné à Paul (DEV)
[INFO] [OK] POT-12 | Bug (Migration échoue...) | IN PROGRESS → BLOCKED | par Paul
[INFO] [COMMENT] Commentaire ajouté sur POT-12 (IN PROGRESS → BLOCKED)
[INFO] [LINK] POT-12 is blocked by POT-19 (ajout automatique)
[INFO] Scénario 'demande_clarification_metier' → ticket KAN-13 [Feature] assigné à Pierre (DEV) → Fatou (BA)
[INFO] [OK] KAN-13 | Feature (Scene 1 hannibal) | IN PROGRESS → — | par Pierre
[INFO] Scénario 'pret_mise_en_service' → ticket POT-15 [Task] statut 'IN REVIEW'
[INFO] [BULK] 3 tickets passés en DONE : POT-15, KAN-13, POT-17
[INFO] Run complete — 10 events executed, 0 skipped
```

---

## Règles

- Python 3.11+, type hints, docstrings en français
- Ne pas modifier `main.py`
- Conserver tous les tests existants
- `load_dotenv()` en première instruction de tout module avec `os.getenv()`
- En mode `--dry-run`, les commentaires Gemini sont générés mais pas postés sur Jira
- `COMMENT_ON_TRANSITION=0.30` par défaut — documenté dans `.env.example`
