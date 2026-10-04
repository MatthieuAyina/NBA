# Agent NBA : interroger trois saisons de NBA en langage naturel

Un pipeline de données complet, de la collecte à l'IA générative : les statistiques NBA de 2023-24 à 2025-26 sont collectées, structurées dans une base DuckDB, puis rendues accessibles par un agent conversationnel. On lui pose une question en français, il écrit ses propres requêtes SQL, vérifie ses résultats et répond.

> *Ajouter ici une capture d'écran ou un GIF de l'application.*

Exemples de questions :
- « Qui a le meilleur pourcentage à 3 points en 2025-26 ? »
- « Combien de points Luka Doncic a-t-il marqués au maximum dans un match cette saison ? »
- « Quel est le meilleur scoreur des Oklahoma City Thunder ? » puis « Et son pourcentage à 3 points ? »

## Les données

Trois saisons complètes (2023-24, 2024-25, 2025-26), en saison régulière et en playoffs, issues de stats.nba.com via la bibliothèque `nba_api` :

- 84 768 feuilles de match (un joueur dans un match) ;
- 700 077 tirs, avec leur position exacte sur le terrain, leur zone et leur distance ;
- les stats avancées (usage, true shooting, net rating, PIE) ;
- les stats de tracking (distance parcourue, vitesse, passes, passes décisives potentielles) ;
- les stats « hustle » (déviations, tirs contestés, passages en force provoqués, écrans).

## Architecture

```
stats.nba.com
     │
     ▼
fetch_nba.py ──► nba_raw/*.csv        Extraction, avec cache et reprise automatique
     │
     ▼
build_nba_db.py ──► nba.duckdb        Nettoyage, modélisation, indicateurs et centiles
     │
     ▼
agent.py                              Agent IA : le modèle écrit et exécute ses requêtes SQL
     │
     ▼
app.py                                Interface de chat (Streamlit)
```

La base contient cinq tables : `games` (feuilles de match), `shots` (tirs), `player_season` (stats par joueur et par saison), `player_shot_zones` (adresse par zone de tir) et `player_percentiles` (position de chaque joueur face aux autres, de 0 à 100).

## Choix techniques et difficultés résolues

**Une collecte qui ne perd rien.** Chaque réponse de NBA.com est enregistrée en CSV avant d'être traitée. Si la collecte s'interrompt (délai dépassé, blocage temporaire), il suffit de relancer le script : il reprend uniquement ce qui manque. Chaque appel est espacé de deux secondes et retenté automatiquement en cas d'échec.

**Des réponses tronquées sans message d'erreur.** Le contrôle des volumes a montré que deux saisons comptaient exactement 102 400 tirs et seulement la moitié des matchs : NBA.com plafonne silencieusement ses réponses à 102 400 lignes. Le script détecte désormais ce plafond et bascule automatiquement sur une collecte équipe par équipe (30 requêtes), dont chacune est mise en cache séparément.

**Séparer extraction et transformation.** La collecte (`fetch_nba.py`) et la construction de la base (`build_nba_db.py`) sont indépendantes. On peut reconstruire la base autant de fois que nécessaire sans solliciter l'API.

**Un agent sûr et vérifiable.** L'agent n'accède jamais directement à la base : il propose une requête, que le code exécute. Deux protections empêchent toute modification des données (seules les requêtes `SELECT` sont acceptées, et la base est ouverte en lecture seule). Les erreurs SQL sont renvoyées au modèle, qui corrige sa requête de lui-même.

**Limiter les hallucinations.** Le prompt système décrit précisément chaque table et liste les données absentes de la base (salaires, blessures, transferts...). L'agent doit alors répondre que l'information n'est pas disponible plutôt que d'inventer un chiffre. Les tests ont aussi révélé des pièges corrigés dans le prompt : les noms accentués (« Dončić » trouvé à partir de « Doncic »), les équipes stockées sous leur abréviation (« OKC ») et le fait qu'un résultat vide ne prouve pas l'absence de données.

**Une conversation suivie.** Les quatre derniers échanges sont transmis à l'agent, qui comprend les questions de suivi comme « Et son pourcentage à 3 points ? ».

## Stack

Python, pandas, DuckDB, nba_api, API Mistral (modèle Mistral Nemo, appel de fonctions), Streamlit.

## Lancer le projet

Prérequis : Python 3.12 et une clé API Mistral (l'offre gratuite suffit).

```
git clone https://github.com/MatthieuAyina/projet-nba.git
cd projet-nba
python -m pip install -r requirements.txt
```

Enregistrer la clé Mistral dans une variable d'environnement (Windows), puis rouvrir le terminal :

```
setx MISTRAL_API_KEY "ta_cle"
```

Collecter les données, construire la base, puis lancer l'application :

```
python fetch_nba.py
python build_nba_db.py --db nba.duckdb
python -m streamlit run app.py
```

La collecte prend une dizaine de minutes. L'agent peut aussi être utilisé directement dans le terminal avec `python agent.py`.

## Limites

- Les données couvrent trois saisons, de 2023-24 à 2025-26.
- L'agent repose sur un petit modèle (Mistral Nemo, offre gratuite). Il peut se tromper sur des questions complexes ; la requête SQL utilisée est affichée dans le terminal pour vérification.
- Les API de stats.nba.com ne sont pas documentées officiellement et peuvent évoluer.

## Données et licence

Les données proviennent de stats.nba.com et restent soumises aux conditions d'utilisation de la NBA. Ce dépôt ne contient aucune donnée : elles sont collectées localement par le script de collecte, dans le cadre d'un projet personnel non commercial.
