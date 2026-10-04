"""
Construit la base DuckDB du projet NBA à partir des CSV de nba_raw/.

Tables créées :
  games               : une ligne par joueur et par match (feuille de match)
  shots               : un tir par ligne, avec sa position et sa zone sur le terrain
  player_season       : stats par joueur et par saison (moyennes, adresse, stats avancées,
                        tracking et hustle)
  player_shot_zones   : tirs tentés, réussis et adresse par zone de tir
  player_percentiles  : centiles (0 à 100) de chaque joueur face aux autres sur la même saison

Usage :
  python build_nba_db.py --db nba.duckdb
"""
import argparse
import glob
import os
import re

import duckdb

RAW_DIR = "nba_raw"
FAMILIES = ["gamelog", "advanced", "shots", "speed_distance", "passing", "hustle"]

# Colonnes reprises des stats avancées, de tracking et hustle : (table brute, colonne NBA, nom dans la base)
EXTRA = [
    ("advanced", "age", "age"),
    ("advanced", "usg_pct", "usage_pct"),
    ("advanced", "off_rating", "off_rating"),
    ("advanced", "def_rating", "def_rating"),
    ("advanced", "net_rating", "net_rating"),
    ("advanced", "ast_pct", "ast_pct"),
    ("advanced", "reb_pct", "reb_pct"),
    ("advanced", "efg_pct", "efg_pct"),
    ("advanced", "pie", "pie"),
    ("advanced", "pace", "pace"),
    ("speed_distance", "dist_miles", "dist_miles"),
    ("speed_distance", "avg_speed", "avg_speed_mph"),
    ("passing", "passes_made", "passes_made"),
    ("passing", "potential_ast", "potential_ast"),
    ("passing", "ast_points_created", "ast_points_created"),
    ("hustle", "deflections", "deflections"),
    ("hustle", "contested_shots", "contested_shots"),
    ("hustle", "charges_drawn", "charges_drawn"),
    ("hustle", "screen_assists", "screen_assists"),
    ("hustle", "loose_balls_recovered", "loose_balls_recovered"),
    ("hustle", "box_outs", "box_outs"),
]

# Indicateurs classés en centiles. True = plus haut est mieux.
PCTL_METRICS = {
    "pts": True, "reb": True, "ast": True, "stl": True, "blk": True, "tov": False,
    "fg3m": True, "fg_pct": True, "fg3_pct": True, "ft_pct": True, "ts_pct": True,
    "usage_pct": True, "net_rating": True, "pie": True, "ast_pct": True, "reb_pct": True,
    "dist_km": True, "deflections": True, "contested_shots": True,
}


def load_raw(con, family):
    """Charge tous les CSV d'une famille, avec la saison et le type de saison tirés du nom du fichier."""
    files = sorted(glob.glob(os.path.join(RAW_DIR, f"{family}_*-*_*.csv")))
    files = [f for f in files if re.search(rf"{family}_\d{{4}}-\d{{2}}_(regular|playoffs)\.csv$", f)]
    if not files:
        print(f"  attention : aucun fichier pour {family}")
        return False
    con.execute(f"""
        CREATE OR REPLACE TABLE raw_{family} AS
        SELECT *,
               regexp_extract(filename, '(\\d{{4}}-\\d{{2}})_(regular|playoffs)', 1) AS season,
               regexp_extract(filename, '(\\d{{4}}-\\d{{2}})_(regular|playoffs)', 2) AS season_type
        FROM read_csv(?, union_by_name = true, filename = true, sample_size = -1)
    """, [files])
    # Noms de colonnes en minuscules, plus simples à écrire en SQL
    cols = [r[0] for r in con.execute(f"DESCRIBE raw_{family}").fetchall()]
    renames = ", ".join(f'"{c}" AS {c.lower()}' for c in cols if c != "filename")
    con.execute(f"CREATE OR REPLACE TABLE raw_{family} AS SELECT {renames} FROM raw_{family}")
    n = con.execute(f"SELECT count(*) FROM raw_{family}").fetchone()[0]
    print(f"  {family} : {n} lignes ({len(files)} fichiers)")
    return True


def columns(con, table):
    return {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}


def build(db_path):
    con = duckdb.connect(db_path)
    print("Chargement des fichiers bruts :")
    present = {f for f in FAMILIES if load_raw(con, f)}
    if "gamelog" not in present:
        raise SystemExit("Les feuilles de match (gamelog) sont indispensables : lance d'abord fetch_nba.py")

    # 1. Feuilles de match
    con.execute("""
        CREATE OR REPLACE TABLE games AS
        SELECT season, season_type, game_id, CAST(game_date AS DATE) AS game_date,
               player_id, player_name, team_abbreviation AS team, matchup,
               matchup LIKE '%vs.%' AS is_home,
               regexp_extract(matchup, '([A-Z]{3})$', 1) AS opponent,
               wl = 'W' AS won, min, pts, reb, oreb, dreb, ast, stl, blk, tov, pf,
               fgm, fga, fg3m, fg3a, ftm, fta, plus_minus
        FROM raw_gamelog
    """)

    # 2. Tirs
    if "shots" in present:
        con.execute("""
            CREATE OR REPLACE TABLE shots AS
            SELECT season, season_type, game_id,
                   strptime(CAST(game_date AS VARCHAR), '%Y%m%d')::DATE AS game_date,
                   player_id, player_name, team_name, period,
                   minutes_remaining, seconds_remaining,
                   action_type, shot_type, shot_zone_basic, shot_zone_area, shot_zone_range,
                   shot_distance, loc_x, loc_y, shot_made_flag = 1 AS made
            FROM raw_shots
        """)
        con.execute("""
            CREATE OR REPLACE TABLE player_shot_zones AS
            SELECT season, season_type, player_id, any_value(player_name) AS player_name,
                   shot_zone_basic AS zone, count(*) AS attempts,
                   sum(CASE WHEN made THEN 1 ELSE 0 END) AS made,
                   round(100.0 * avg(CASE WHEN made THEN 1 ELSE 0 END), 1) AS pct
            FROM shots GROUP BY season, season_type, player_id, shot_zone_basic
        """)

    # 3. Stats par joueur et par saison (moyennes par match calculées depuis les feuilles de match)
    joins, extra_cols = [], []
    for family in ("advanced", "speed_distance", "passing", "hustle"):
        if family not in present:
            continue
        available = columns(con, f"raw_{family}")
        picked = [(src, dst) for fam, src, dst in EXTRA if fam == family and src in available]
        missing = [src for fam, src, _ in EXTRA if fam == family and src not in available]
        if missing:
            print(f"  colonnes absentes dans {family} (ignorées) : {', '.join(missing)}")
        if picked:
            alias = family[:3]
            joins.append(f"LEFT JOIN raw_{family} {alias} USING (season, season_type, player_id)")
            extra_cols += [f"{alias}.{src} AS {dst}" for src, dst in picked]
    extra_sql = (",\n               " + ",\n               ".join(extra_cols)) if extra_cols else ""

    con.execute(f"""
        CREATE OR REPLACE TABLE player_season AS
        WITH g AS (
            SELECT season, season_type, player_id,
                   arg_max(player_name, game_date) AS player_name,
                   arg_max(team, game_date) AS team,
                   count(*) AS gp, sum(CASE WHEN won THEN 1 ELSE 0 END) AS wins,
                   round(avg(min), 1) AS min, round(avg(pts), 1) AS pts, round(avg(reb), 1) AS reb,
                   round(avg(ast), 1) AS ast, round(avg(stl), 1) AS stl, round(avg(blk), 1) AS blk,
                   round(avg(tov), 1) AS tov, round(avg(fg3m), 1) AS fg3m,
                   round(avg(plus_minus), 1) AS plus_minus,
                   sum(pts) AS total_pts, sum(fga) AS total_fga, sum(fg3a) AS total_fg3a,
                   round(100.0 * sum(fgm) / nullif(sum(fga), 0), 1) AS fg_pct,
                   round(100.0 * sum(fg3m) / nullif(sum(fg3a), 0), 1) AS fg3_pct,
                   round(100.0 * sum(ftm) / nullif(sum(fta), 0), 1) AS ft_pct,
                   round(100.0 * sum(pts) / nullif(2 * (sum(fga) + 0.44 * sum(fta)), 0), 1) AS ts_pct
            FROM games GROUP BY season, season_type, player_id
        )
        SELECT g.*{extra_sql}
        FROM g
        {" ".join(joins)}
    """)
    cols = columns(con, "player_season")
    # Pourcentages des stats avancées en 0-100, et distance en kilomètres
    for c in ("usage_pct", "ast_pct", "reb_pct", "efg_pct", "pie"):
        if c in cols:
            con.execute(f"UPDATE player_season SET {c} = round(100 * {c}, 1) WHERE {c} <= 1")
    if "dist_miles" in cols:
        con.execute("ALTER TABLE player_season ADD COLUMN dist_km DOUBLE")
        con.execute("UPDATE player_season SET dist_km = round(dist_miles * 1.609, 2)")
        con.execute("ALTER TABLE player_season DROP COLUMN dist_miles")
        cols = columns(con, "player_season")

    # 4. Centiles : saison régulière >= 40 matchs, playoffs >= 6 matchs
    metrics = [m for m in PCTL_METRICS if m in cols]
    pct_cols = ",\n            ".join(
        f"round(100 * percent_rank() OVER (PARTITION BY season, season_type "
        f"ORDER BY {m} {'ASC' if PCTL_METRICS[m] else 'DESC'} NULLS FIRST))::INT AS {m}_pctl"
        for m in metrics)
    con.execute(f"""
        CREATE OR REPLACE TABLE player_percentiles AS
        SELECT season, season_type, player_id, player_name, team, gp,
            {pct_cols}
        FROM player_season
        WHERE (season_type = 'regular' AND gp >= 40) OR (season_type = 'playoffs' AND gp >= 6)
    """)

    # Nettoyage des tables brutes et résumé
    for f in present:
        con.execute(f"DROP TABLE raw_{f}")
    print("\nTables créées :")
    with open("schema.txt", "w", encoding="utf-8") as out:
        for (t,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
            n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            cs = [r[0] for r in con.execute(f"DESCRIBE {t}").fetchall()]
            print(f"  {t} : {n} lignes")
            out.write(f"{t} ({n} lignes) : {', '.join(cs)}\n")
    print("Liste des colonnes écrite dans schema.txt")

    top = con.execute("""
        SELECT player_name, team, gp, pts, ts_pct FROM player_season
        WHERE season = (SELECT max(season) FROM player_season) AND season_type = 'regular' AND gp >= 50
        ORDER BY pts DESC LIMIT 5
    """).fetchdf()
    print("\nContrôle, meilleurs marqueurs de la dernière saison :")
    print(top.to_string(index=False))
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nba.duckdb")
    args = parser.parse_args()
    build(args.db)
