from nba_api.stats.endpoints import leaguegamelog

# Un seul appel : la ligne de stats de chaque joueur pour chaque match de la saison
log = leaguegamelog.LeagueGameLog(
    season="2025-26",
    season_type_all_star="Regular Season",
    player_or_team_abbreviation="P",
    timeout=60,
)
df = log.get_data_frames()[0]

print(len(df), "lignes (un joueur dans un match)")
print("Colonnes :", df.columns.tolist())

# Petit contrôle : les meilleurs marqueurs (au moins 50 matchs joués)
moyennes = df.groupby("PLAYER_NAME").agg(matchs=("PTS", "size"), points=("PTS", "mean"))
print(moyennes[moyennes.matchs >= 50].sort_values("points", ascending=False).head(5).round(1))