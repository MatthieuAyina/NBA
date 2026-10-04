"""
Collecte des données NBA via nba_api (site stats.nba.com).

Chaque réponse est enregistrée en CSV dans nba_raw/. Une donnée déjà enregistrée
n'est jamais redemandée : si le script s'arrête (coupure, délai dépassé), il suffit
de le relancer pour qu'il reprenne là où il en était.

Usage :
  python fetch_nba.py
  python fetch_nba.py --seasons 2025-26        (une seule saison)
"""
import argparse
import os
import time

import pandas as pd

from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    leaguedashptstats,
    leaguegamelog,
    leaguehustlestatsplayer,
    shotchartdetail,
)
from nba_api.stats.static import teams

RAW_DIR = "nba_raw"
SEASON_TYPES = {"Regular Season": "regular", "Playoffs": "playoffs"}
PAUSE = 2  # secondes entre deux appels, pour ne pas être bloqué par NBA.com
ROW_CAP = 102_400  # NBA.com tronque silencieusement les réponses à ce nombre de lignes


def datasets(season, season_type):
    """Liste des données à récupérer pour une saison : (nom du fichier, fonction d'appel)."""
    common = dict(season=season, season_type_all_star=season_type, timeout=120)
    return [
        ("gamelog", lambda: leaguegamelog.LeagueGameLog(
            player_or_team_abbreviation="P", **common).get_data_frames()[0]),
        ("advanced", lambda: leaguedashplayerstats.LeagueDashPlayerStats(
            measure_type_detailed_defense="Advanced", per_mode_detailed="PerGame",
            **common).get_data_frames()[0]),
        ("shots", lambda: shotchartdetail.ShotChartDetail(
            team_id=0, player_id=0, context_measure_simple="FGA",  # FGA = tous les tirs, réussis ou non
            season_nullable=season, season_type_all_star=season_type,
            timeout=180).get_data_frames()[0]),
        ("speed_distance", lambda: leaguedashptstats.LeagueDashPtStats(
            player_or_team="Player", pt_measure_type="SpeedDistance",
            per_mode_simple="PerGame", **common).get_data_frames()[0]),
        ("passing", lambda: leaguedashptstats.LeagueDashPtStats(
            player_or_team="Player", pt_measure_type="Passing",
            per_mode_simple="PerGame", **common).get_data_frames()[0]),
        ("hustle", lambda: leaguehustlestatsplayer.LeagueHustleStatsPlayer(
            per_mode_time="PerGame", **common).get_data_frames()[0]),
    ]


def try_call(call, label, attempts=3):
    """Exécute un appel avec plusieurs tentatives. Renvoie le tableau, ou None en cas d'échec."""
    for attempt in range(1, attempts + 1):
        try:
            time.sleep(PAUSE)
            return call()
        except Exception as e:
            print(f"  tentative {attempt}/{attempts} échouée pour {label} : {str(e)[:100]}")
            time.sleep(10 * attempt)
    return None


def shots_by_team(season, season_type, name):
    """Repli : récupère les tirs équipe par équipe (30 petites requêtes), puis les rassemble."""
    team_dir = os.path.join(RAW_DIR, name + "_par_equipe")
    os.makedirs(team_dir, exist_ok=True)
    parts = []
    for t in teams.get_teams():
        path = os.path.join(team_dir, f"{t['abbreviation']}.csv")
        if not os.path.exists(path):
            df = try_call(lambda: shotchartdetail.ShotChartDetail(
                team_id=t["id"], player_id=0, context_measure_simple="FGA",
                season_nullable=season, season_type_all_star=season_type,
                timeout=120).get_data_frames()[0], f"{name} {t['abbreviation']}")
            if df is None:
                print(f"  ABANDON pour {name} ({t['abbreviation']}), relance le script plus tard")
                return None
            df.to_csv(path, index=False)
            print(f"    {t['abbreviation']} : {len(df)} tirs")
        parts.append(pd.read_csv(path))
    return pd.concat(parts, ignore_index=True)


def fetch(name, call, season, season_type):
    """Récupère une donnée (avec cache) et l'enregistre en CSV."""
    path = os.path.join(RAW_DIR, name + ".csv")
    if os.path.exists(path):
        print(f"  déjà en cache : {name}")
        return
    df = try_call(call, name)
    if name.startswith("shots") and (df is None or len(df) >= ROW_CAP):
        reason = "réponse tronquée par NBA.com" if df is not None else "requête trop lourde"
        print(f"  {reason} pour {name} : récupération équipe par équipe")
        df = shots_by_team(season, season_type, name)
    if df is None:
        print(f"  ABANDON pour {name}, relance le script plus tard")
        return
    df.to_csv(path, index=False)
    print(f"  OK : {name} ({len(df)} lignes)")


def main(seasons):
    os.makedirs(RAW_DIR, exist_ok=True)
    for season in seasons:
        for season_type, short in SEASON_TYPES.items():
            print(f"Saison {season} ({season_type})")
            for name, call in datasets(season, season_type):
                fetch(f"{name}_{season}_{short}", call, season, season_type)
    print("Collecte terminée.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", default=["2023-24", "2024-25", "2025-26"])
    args = parser.parse_args()
    main(args.seasons)
