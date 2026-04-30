"""Quick stats: niche-flag rates per channel + a few examples of high-niche titles."""

from __future__ import annotations

import duckdb

con = duckdb.connect("data/warehouse.duckdb")

print("-- per-channel niche flag rates --------------------------------------------------")
header = f"{'channel':<28}{'n':>6}{'caps':>7}{'num':>7}{'emoji':>7}{'rank':>7}{'expl':>7}{'curi':>7}{'extr':>7}{'fp':>7}"
print(header)
print("-" * len(header))
for r in con.execute("""
    SELECT c.title,
           COUNT(*) AS n,
           AVG(CAST(f.has_caps_word AS INT))*100,
           AVG(CAST(f.has_number AS INT))*100,
           AVG(CAST(f.has_emoji AS INT))*100,
           AVG(CAST(f.has_ranking_keyword AS INT))*100,
           AVG(CAST(f.has_explained_keyword AS INT))*100,
           AVG(CAST(f.has_curiosity_keyword AS INT))*100,
           AVG(CAST(f.has_extreme_adjective AS INT))*100,
           AVG(CAST(f.has_first_person AS INT))*100
    FROM channels c
    JOIN videos v ON v.channel_id = c.id
    JOIN video_features f ON f.video_id = v.id
    GROUP BY c.title
    ORDER BY n DESC
""").fetchall():
    name = (r[0] or "")[:26]
    rates = "".join(f"{x:>6.0f}%" for x in r[2:])
    print(f"{name:<28}{r[1]:>6}{rates}")

print()
print("-- top 8 titulos com niche_score >= 5 (ranking/explicado/curiosidade/etc) -------")
for r in con.execute("""
    SELECT c.title AS ch, v.title, vs.views,
           (CAST(f.has_explained_keyword AS INT) + CAST(f.has_ranking_keyword AS INT)
            + CAST(f.has_curiosity_keyword AS INT) + CAST(f.has_extreme_adjective AS INT)
            + CAST(f.has_caps_word AS INT) + CAST(f.has_emoji AS INT)
            + CAST(f.has_number AS INT) + CAST(f.has_question_mark AS INT)) AS niche_score
    FROM channels c
    JOIN videos v ON v.channel_id = c.id
    JOIN video_features f ON f.video_id = v.id
    JOIN video_stats_snapshots vs ON vs.video_id = v.id
    WHERE niche_score >= 5
    ORDER BY vs.views DESC LIMIT 8
""").fetchall():
    print(f"   [{(r[0] or '')[:18]:<18}] sc={r[3]} {r[2]:>10,} v  {r[1][:65]}")
