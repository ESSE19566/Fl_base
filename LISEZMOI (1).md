# ESSE Fleet

Application de gestion de flottes de taxis pensée pour le marché congolais (Pointe-Noire, Brazzaville), avec extension prévue en Afrique centrale. Elle permet de suivre :

- les **véhicules** (taxis) et leur état ;
- les **chauffeurs** et l'historique de leurs affectations ;
- les **recettes** et **dépenses** (en FCFA), jour par jour, avec motif des dépenses ;
- la **maintenance** (pannes, entretiens) ;
- **ESSE AI**, un assistant qui aide à analyser l'activité et à décider.

> **Statut : base de développement.** Le projet n'est pas prêt pour la production (voir « Limites connues »).

## Technologies

- Backend : Python 3.10+, FastAPI, SQLite (module standard `sqlite3`), httpx
- Interface : un seul fichier HTML/CSS/JavaScript (`ESSE-Fleet.html`), servi par le backend
- IA : API OpenAI, appelée **uniquement depuis le serveur**
- Tests : pytest

## Contenu du dépôt

```
ESSE_Fleet/
├── main.py            serveur FastAPI
├── ESSE-Fleet.html    application (interface)
├── requirements.txt   dépendances Python
├── test_smoke.py      tests automatiques
├── LISEZMOI.md        ce fichier
├── .env.example       modèle de configuration (sans secret)
├── .gitignore         exclut .env, données locales, caches
└── data/              base SQLite créée automatiquement (non publiée)
```

## Installation

```
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration (.env)

```
cp .env.example .env               # Windows : copy .env.example .env
```

Éditez ensuite `.env`. Pour activer ESSE AI, renseignez `OPENAI_API_KEY`. Sans clé, tout fonctionne sauf les réponses réelles de l'IA : l'application utilise alors sa simulation locale. Le budget mensuel d'ESSE AI se règle avec `AI_MONTHLY_BUDGET_USD` ; ajustez aussi `AI_PRICE_IN_PER_M` et `AI_PRICE_OUT_PER_M` selon le modèle.

## Démarrer

```
uvicorn main:app --reload --port 8000
```

Ouvrez **http://localhost:8000** dans le navigateur (et non le fichier HTML directement). Contrôle rapide : http://localhost:8000/health. La base `data/esse_fleet.sqlite3` est créée au premier lancement.

## Tests

```
pip install pytest
pytest -q
```

Les tests utilisent une base temporaire, des données fictives et une IA simulée : aucune clé ni requête réseau n'est nécessaire. Ils vérifient aussi que chaque appel du fichier HTML correspond à une route du serveur.

## Précautions de sécurité

- Ne publiez **jamais** `.env`, la clé OpenAI, ni le dossier `data/` (base de données réelle). `.gitignore` les exclut, mais vérifiez avant chaque envoi.
- Si une clé a été publiée par erreur, **révoquez-la** chez OpenAI immédiatement et créez-en une nouvelle : la supprimer du dépôt ne suffit pas, l'historique la conserve.
- N'ajoutez aucune donnée réelle (noms, téléphones, e-mails de vrais clients ou chauffeurs) dans les tests ou la documentation.
- Les mots de passe sont stockés hachés (scrypt) et les sessions expirent au bout de 30 jours.
- Les données de chaque entreprise sont isolées côté serveur.

## Limites connues (avant toute mise en production)

- Mettre l'application derrière **HTTPS** (certificat, proxy) et définir `TRUST_PROXY=1` si un proxy est utilisé.
- Pas encore de mot de passe oublié, ni de vérification d'e-mail, ni d'invitation de gestionnaires, mécaniciens ou chauffeurs (les rôles existent côté serveur).
- Limitation de débit en mémoire (par processus) ; SQLite convient à un serveur unique. Une montée en charge importante (plusieurs entreprises, milliers de véhicules) demandera PostgreSQL, la pagination des données et des sauvegardes régulières.
- ESSE AI lit les données de la flotte mais n'exécute aucune action : les actions proposées dans l'interface restent confirmées par l'utilisateur.
