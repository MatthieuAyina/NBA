import json
import os
import time

import duckdb
from mistralai.client import Mistral

DB_PATH = "nba.duckdb"
MAX_ROWS = 50
MODEL = "open-mistral-nemo"
client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

SYSTEM_PROMPT = """Tu es un analyste data spécialisé dans la NBA.
Tu interroges une base DuckDB qui couvre les saisons 2023-24, 2024-25 et 2025-26 (saison régulière et playoffs).

TABLES DISPONIBLES

player_season : statistiques d'un joueur par saison.
  season ('2023-24', '2024-25', '2025-26'), season_type ('regular' ou 'playoffs'),
  player_id, player_name, team (dernière équipe), age, gp (matchs joués), wins,
  Moyennes par match : min, pts, reb, ast, stl, blk, tov, fg3m (3 points réussis), plus_minus.
  Totaux : total_pts, total_fga, total_fg3a.
  Adresse en % (0 à 100) : fg_pct, fg3_pct, ft_pct, ts_pct (true shooting), efg_pct.
  Stats avancées : usage_pct, ast_pct, reb_pct, pie (en %), off_rating, def_rating, net_rating, pace.
  Tracking (par match) : dist_km (distance parcourue), avg_speed_mph, passes_made, potential_ast,
  ast_points_created.
  Hustle (par match) : deflections, contested_shots, charges_drawn, screen_assists,
  loose_balls_recovered, box_outs.

player_percentiles : centiles (0 à 100, 100 = le meilleur) des joueurs ayant au moins
  40 matchs en saison régulière ou 6 en playoffs.
  season, season_type, player_id, player_name, team, gp, et une colonne <indicateur>_pctl
  (ex. pts_pctl, ts_pct_pctl, usage_pct_pctl, deflections_pctl, dist_km_pctl).

games : une ligne par joueur et par match.
  season, season_type, game_id, game_date, player_id, player_name, team, matchup,
  is_home, opponent, won, min, pts, reb, oreb, dreb, ast, stl, blk, tov, pf,
  fgm, fga, fg3m, fg3a, ftm, fta, plus_minus.

shots : un tir par ligne (700 000 tirs).
  season, season_type, game_id, game_date, player_id, player_name, team_name, period,
  minutes_remaining, seconds_remaining, action_type (ex. 'Jump Shot', 'Driving Layup Shot'),
  shot_type ('2PT Field Goal' ou '3PT Field Goal'),
  shot_zone_basic ('Restricted Area', 'In The Paint (Non-RA)', 'Mid-Range', 'Left Corner 3',
                   'Right Corner 3', 'Above the Break 3', 'Backcourt'),
  shot_zone_area, shot_zone_range, shot_distance (en pieds), loc_x, loc_y, made (booléen).

player_shot_zones : par joueur, saison et zone : season, season_type, player_id, player_name,
  zone, attempts, made, pct.

RÈGLES
- Pour les stats d'une saison, utilise player_season ou player_percentiles.
  Utilise games pour un match précis ou des records sur un match, shots pour les tirs.
- Sans précision, utilise la saison la plus récente ('2025-26') et season_type = 'regular'.
- Pour classer des joueurs sur une moyenne ou un pourcentage, écarte les petits échantillons :
  gp >= 40 en saison régulière, gp >= 6 en playoffs. Pour l'adresse à 3 points, ajoute aussi
  total_fg3a >= 150.
- Les noms contiennent des accents (ex. 'Luka Dončić', 'Nikola Jokić'). Cherche toujours un joueur
  avec strip_accents(player_name) ILIKE '%doncic%'.
- Les colonnes team et opponent contiennent l'abréviation à 3 lettres de l'équipe :
  ATL Atlanta Hawks, BOS Boston Celtics, BKN Brooklyn Nets, CHA Charlotte Hornets,
  CHI Chicago Bulls, CLE Cleveland Cavaliers, DAL Dallas Mavericks, DEN Denver Nuggets,
  DET Detroit Pistons, GSW Golden State Warriors, HOU Houston Rockets, IND Indiana Pacers,
  LAC LA Clippers, LAL Los Angeles Lakers, MEM Memphis Grizzlies, MIA Miami Heat,
  MIL Milwaukee Bucks, MIN Minnesota Timberwolves, NOP New Orleans Pelicans,
  NYK New York Knicks, OKC Oklahoma City Thunder, ORL Orlando Magic, PHI Philadelphia 76ers,
  PHX Phoenix Suns, POR Portland Trail Blazers, SAC Sacramento Kings, SAS San Antonio Spurs,
  TOR Toronto Raptors, UTA Utah Jazz, WAS Washington Wizards.
- Pour les stats d'un joueur avec une équipe précise, calcule à partir de games avec team = '<abréviation>',
  car player_season.team ne contient que la dernière équipe d'un joueur transféré.
- Un résultat vide ne prouve pas que la donnée n'existe pas. Avant de conclure, vérifie les valeurs
  réelles de la colonne (ex. SELECT DISTINCT team FROM games) et corrige ta requête.
- La base ne contient PAS : salaires, contrats, blessures, transferts, draft, stats universitaires,
  compositions d'équipe, défense individuelle face à un joueur précis, saisons avant 2023-24.
  Si la question porte sur ces sujets, réponds clairement que la donnée n'est pas disponible,
  sans faire de calcul, puis propose un indicateur proche qui existe.
- Ne fais jamais d'estimation pour remplacer une donnée manquante. Ne donne que des chiffres
  qui sortent directement d'une requête.
- Limite toujours les résultats avec LIMIT (20 maximum).
- Utilise l'outil run_sql pour obtenir les données. N'invente jamais de chiffres.
- Si une requête renvoie une erreur ou un résultat vide, corrige-la et réessaie.
- Réponds en français, de façon concise, en citant les chiffres obtenus.
"""


def run_sql(query):
    """Exécute une requête en lecture seule. Renvoie un tableau, ou un message d'erreur."""
    q = query.strip().rstrip(";")

    # Protection 1 : uniquement des lectures
    if not q.lower().startswith(("select", "with")):
        return "Erreur : seules les requêtes SELECT sont autorisées."

    # Protection 2 : base ouverte en lecture seule
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        df = con.execute(q).fetchdf()
        con.close()
    except Exception as e:
        return f"Erreur SQL : {e}"

    return df.head(MAX_ROWS)


# Description de l'outil, telle que le modèle la voit
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Exécute une requête SQL SELECT sur la base NBA et renvoie le résultat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "La requête SQL DuckDB à exécuter."}
                },
                "required": ["query"],
            },
        },
    }
]


def call_model(messages):
    """Appelle Mistral, avec 3 tentatives en cas de limite de débit (erreur 429)."""
    for attempt in range(3):
        try:
            return client.chat.complete(model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto")
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(5)
            else:
                raise


def ask_agent(question, history=None, max_steps=5):
    """Fait tourner l'agent jusqu'à ce qu'il réponde. Renvoie la réponse et les tableaux obtenus."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Les 4 derniers échanges, pour que l'agent comprenne les questions de suivi
    for previous_question, previous_answer in (history or [])[-4:]:
        messages.append({"role": "user", "content": previous_question})
        messages.append({"role": "assistant", "content": previous_answer})
    messages.append({"role": "user", "content": question})
    tables = []

    for step in range(max_steps):
        message = call_model(messages).choices[0].message

        # Pas de demande d'outil : le modèle a fini, on renvoie sa réponse
        if not message.tool_calls:
            return message.content, tables

        # On garde dans l'historique la demande d'outil du modèle
        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in message.tool_calls
            ],
        })

        # On exécute chaque requête demandée et on renvoie le résultat au modèle
        for tc in message.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                args = json.loads(args)
            query = args["query"]
            print(f"\n[Requête n°{step + 1}]\n{query}")

            result = run_sql(query)
            if isinstance(result, str):
                content = result  # message d'erreur
            elif result.empty:
                content = "Aucune ligne trouvée."
            else:
                tables.append((query, result))
                content = result.to_csv(index=False)

            messages.append({"role": "tool", "name": "run_sql", "content": content, "tool_call_id": tc.id})
        time.sleep(1)  # on respecte la limite de l'offre gratuite

    return "Je n'ai pas réussi à répondre en 5 étapes.", tables


if __name__ == "__main__":
    print("Agent NBA. Tape ta question, ou 'q' pour quitter.")
    history = []
    while True:
        question = input("\nQuestion : ")
        if question.strip().lower() == "q":
            break
        answer, tables = ask_agent(question, history)
        history.append((question, answer))
        print(f"\nRéponse :\n{answer}")