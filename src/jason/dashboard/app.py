"""JASON dashboard — Streamlit, 6 abas (Fase 5 + UI overhaul).

Run with: `uv run jason dashboard`

Each tab gracefully degrades when its data dependency isn't ready yet
(e.g. no outliers populated, no model artifact). The point is to be
useful from day 1 even before all the ML pieces have produced output.

UI: brutalist hauntology — bone on near-black, blood-red used sparingly,
typewriter headings, sharp corners. No gradients. No glow. No "AI vibes".
"""

from __future__ import annotations

import duckdb
import pandas as pd
import streamlit as st

from jason.config import get_settings

st.set_page_config(
    page_title="JASON",
    page_icon=":skull:",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --- global style ---------------------------------------------------------

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Special+Elite&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background: #0E0E0E;
    color: #E8E5DE;
    font-family: 'Inter', system-ui, sans-serif;
}

h1, h2, h3, h4, h5, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
    font-family: 'Special Elite', 'Courier New', monospace;
    color: #E8E5DE !important;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    font-weight: 400;
    margin-bottom: 0.4rem;
}
h1 { font-size: 2.2rem; border-bottom: 2px solid #B11C19; padding-bottom: 0.4rem; margin-bottom: 1rem; }
h2 { font-size: 1.4rem; margin-top: 1.2rem; }
h3 { font-size: 1.1rem; }

p, .stMarkdown p, .stCaption, [data-testid="stCaptionContainer"] {
    color: #B0AEA8;
    font-family: 'Inter', sans-serif;
}

code, pre {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    background: #161616 !important;
    color: #E8E5DE !important;
    border-radius: 0 !important;
}

button, .stButton button, .stTextInput input, .stTextArea textarea,
.stNumberInput input, .stSelectbox > div, [data-baseweb="select"] > div,
[data-testid="stMetric"], .stRadio > div, .stSlider [data-baseweb="slider"] {
    border-radius: 0 !important;
}

.stButton > button {
    background: transparent;
    border: 1px solid #B11C19;
    color: #E8E5DE;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 500;
    padding: 0.5rem 1.2rem;
    transition: background 0.12s;
}
.stButton > button:hover {
    background: #B11C19;
    color: #0E0E0E;
    border-color: #B11C19;
}

[data-testid="stMetric"] {
    background: #141414;
    border: 1px solid #2A2A2A;
    padding: 0.9rem 1rem;
}
[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    font-size: 1.7rem;
    color: #E8E5DE;
}
[data-testid="stMetricLabel"] {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.7rem;
    color: #888880;
}

.stTabs [data-baseweb="tab-list"] {
    border-bottom: 1px solid #2A2A2A;
    gap: 0;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    border-radius: 0 !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.78rem;
    font-weight: 500;
    border-bottom: 2px solid transparent !important;
    color: #888880;
    padding: 0.6rem 1.2rem;
}
.stTabs [aria-selected="true"] {
    border-bottom: 2px solid #B11C19 !important;
    color: #E8E5DE !important;
}

#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] { visibility: hidden; }

[data-testid="stDataFrame"] {
    background: #141414;
    border: 1px solid #2A2A2A;
}

a, a:visited { color: #B11C19; }
a:hover { color: #E8E5DE; }

hr { border: 0; border-top: 1px solid #2A2A2A; margin: 1.5rem 0; }

.jason-mast {
    font-family: 'Special Elite', monospace;
    border-bottom: 2px solid #B11C19;
    padding-bottom: 0.6rem;
    margin-bottom: 1rem;
}
.jason-mast .name {
    font-size: 2.2rem;
    letter-spacing: 0.08em;
    color: #E8E5DE;
}
.jason-mast .sub {
    font-size: 0.78rem;
    letter-spacing: 0.18em;
    color: #888880;
    text-transform: uppercase;
}

.jason-pill {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border: 1px solid #2A2A2A;
    color: #E8E5DE;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    letter-spacing: 0.05em;
    margin-right: 0.4rem;
}
.jason-pill-hot { border-color: #B11C19; color: #B11C19; }
.jason-pill-mid { border-color: #D4AF37; color: #D4AF37; }
</style>
"""

st.markdown(_CSS, unsafe_allow_html=True)
st.markdown(
    '<div class="jason-mast">'
    '<div class="name">J A S O N</div>'
    '<div class="sub">youtube outlier intelligence · @babygiulybaby</div>'
    "</div>",
    unsafe_allow_html=True,
)


# --- shared --------------------------------------------------------------


@st.cache_resource
def _con() -> duckdb.DuckDBPyConnection:
    settings = get_settings()
    return duckdb.connect(str(settings.duckdb_path), read_only=True)


def _pill(text: str, kind: str = "") -> str:
    cls = "jason-pill" + (f" jason-pill-{kind}" if kind else "")
    return f'<span class="{cls}">{text}</span>'


def _multiplier_pill(mult: float) -> str:
    if mult >= 3.0:
        return _pill(f"{mult:.1f}x", "hot")
    if mult >= 1.5:
        return _pill(f"{mult:.1f}x", "mid")
    return _pill(f"{mult:.1f}x")


# --- tabs ----------------------------------------------------------------


def _tab_outliers() -> None:
    st.header("Outliers do nicho")
    st.caption(
        "Ranqueado por percentile_in_channel (90+ é outlier oficial). "
        "Quando vazio, ainda não há ~28 dias de snapshot — usa fallback de top views."
    )

    con = _con()
    channels = con.execute("SELECT id, title FROM channels ORDER BY title").fetchall()
    channel_filter = st.selectbox(
        "Canal", ["(todos)"] + [f"{t} ({i})" for i, t in channels],
    )

    sql = """
        SELECT v.id, v.title, c.title AS channel,
               COALESCE(o.percentile_in_channel, 0.0) AS pct,
               COALESCE(o.multiplier, 0.0)            AS mult,
               latest.views,
               v.thumbnail_url, f.theme_label, f.franchise_label
        FROM videos v
        JOIN channels c ON c.id = v.channel_id
        LEFT JOIN video_features f ON f.video_id = v.id
        LEFT JOIN outliers o ON o.video_id = v.id
        LEFT JOIN (
            SELECT video_id, MAX(views) AS views
            FROM video_stats_snapshots GROUP BY video_id
        ) latest ON latest.video_id = v.id
        WHERE v.is_short = false
    """
    params: list = []
    if channel_filter != "(todos)":
        cid = channel_filter[channel_filter.rfind("(") + 1 : -1]
        sql += " AND v.channel_id = ?"
        params.append(cid)

    has_pct = con.execute(
        "SELECT COUNT(*) FROM outliers WHERE percentile_in_channel IS NOT NULL"
    ).fetchone()[0]
    sql += " ORDER BY pct DESC, mult DESC LIMIT 50" if has_pct else " ORDER BY latest.views DESC LIMIT 50"

    df = con.execute(sql, params).df()
    if df.empty:
        st.info("Sem vídeos no DB ainda. Rode `jason ingest channels`.")
        return

    if not has_pct:
        st.warning(
            "outliers.percentile_in_channel ainda vazio — exibindo por views. "
            "Rode `jason features outliers --live` ou aguarde ~28 dias de snapshot."
        )

    for _, row in df.head(20).iterrows():
        cols = st.columns([1, 4])
        with cols[0]:
            if row.get("thumbnail_url"):
                st.image(row["thumbnail_url"], width=160)
        with cols[1]:
            st.markdown(f"**[{row['channel']}]** {row['title']}")
            pills = ""
            if row["pct"]:
                pills += _pill(f"p{row['pct']:.0f}", "hot" if row["pct"] >= 95 else "mid")
            if row["mult"]:
                pills += _multiplier_pill(row["mult"])
            if row["views"]:
                pills += _pill(f"{int(row['views']):,} v")
            if row.get("theme_label"):
                pills += _pill(f"theme: {row['theme_label']}")
            if row.get("franchise_label"):
                pills += _pill(f"franchise: {row['franchise_label']}")
            st.markdown(pills, unsafe_allow_html=True)
            st.markdown(f"[abrir no YouTube ↗](https://youtu.be/{row['id']})")


def _tab_own_performance() -> None:
    st.header("Performance própria")
    st.caption(
        "Análises do canal @babygiulybaby contra os outliers do nicho. "
        "CTR / AVD / retenção exigem OAuth do YouTube Analytics — rode `jason analytics auth`."
    )

    settings = get_settings()
    own = settings.own_channel_id
    con = _con()

    own_count = con.execute(
        "SELECT COUNT(*) FROM videos WHERE channel_id = ? AND is_short = false",
        [own],
    ).fetchone()[0]
    if own_count == 0:
        st.info(f"Canal próprio ({own}) sem dados ainda. Rode `jason ingest channels --ids {own}`.")
        return

    # Top metrics
    metrics = con.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM videos WHERE channel_id = ? AND is_short = false) AS long_videos,
          (SELECT MAX(published_at) FROM videos WHERE channel_id = ?) AS last_upload,
          (SELECT MAX(o.multiplier) FROM outliers o
             JOIN videos v ON v.id = o.video_id WHERE v.channel_id = ?) AS top_mult,
          (SELECT COUNT(*) FROM outliers o
             JOIN videos v ON v.id = o.video_id
            WHERE v.channel_id = ? AND o.multiplier >= 1.5) AS soft_outliers
        """,
        [own, own, own, own],
    ).fetchone()
    long_videos, last_upload, top_mult, soft_outliers = metrics

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Long-form vídeos", f"{long_videos:,}")
    c2.metric("Último upload", last_upload.strftime("%Y-%m-%d") if last_upload else "—")
    c3.metric("Maior multiplier", f"{top_mult:.2f}x" if top_mult else "—")
    c4.metric("Soft outliers (≥1.5x)", f"{soft_outliers:,}")

    st.markdown("---")

    # Outlier ranking — own channel, top by multiplier
    st.subheader("Teus outliers")
    own_outliers = con.execute(
        """
        SELECT v.id, v.title, v.published_at, v.thumbnail_url,
               o.multiplier, o.percentile_in_channel,
               latest.views, f.theme_label, f.franchise_label
        FROM videos v
        JOIN outliers o ON o.video_id = v.id
        LEFT JOIN video_features f ON f.video_id = v.id
        LEFT JOIN (
            SELECT video_id, MAX(views) AS views
            FROM video_stats_snapshots GROUP BY video_id
        ) latest ON latest.video_id = v.id
        WHERE v.channel_id = ? AND v.is_short = false
        ORDER BY o.multiplier DESC
        LIMIT 10
        """,
        [own],
    ).df()

    if own_outliers.empty:
        st.info("Sem multiplier calculado pros teus vídeos ainda. "
                "Rode `jason features outliers --live`.")
    else:
        for _, row in own_outliers.iterrows():
            cols = st.columns([1, 4])
            with cols[0]:
                if row.get("thumbnail_url"):
                    st.image(row["thumbnail_url"], width=140)
            with cols[1]:
                st.markdown(f"**{row['title']}**")
                pills = _multiplier_pill(row["multiplier"])
                if row["percentile_in_channel"]:
                    pct = row["percentile_in_channel"]
                    pills += _pill(f"p{pct:.0f}", "hot" if pct >= 95 else "mid")
                if row["views"]:
                    pills += _pill(f"{int(row['views']):,} v")
                if row.get("theme_label"):
                    pills += _pill(f"theme: {row['theme_label']}")
                st.markdown(pills, unsafe_allow_html=True)
                st.markdown(
                    f"<span style='color:#888880'>{row['published_at'].strftime('%Y-%m-%d')} · "
                    f"<a href='https://youtu.be/{row['id']}'>↗</a></span>",
                    unsafe_allow_html=True,
                )

    st.markdown("---")

    # Packaging gap vs niche outliers
    st.subheader("Gap de packaging vs outliers do nicho")
    st.caption(
        "Quanto seu padrão de título usa cada flag, vs quanto os outliers (p≥90) "
        "do nicho usam. Diff negativo = você usa MENOS que o que viraliza."
    )
    gap = con.execute(
        """
        WITH own_stats AS (
            SELECT
                AVG(CAST(f.has_caps_word AS INT))            AS caps_word,
                AVG(CAST(f.has_number AS INT))               AS number,
                AVG(CAST(f.has_question_mark AS INT))        AS question,
                AVG(CAST(f.has_emoji AS INT))                AS emoji,
                AVG(CAST(f.has_first_person AS INT))         AS first_person,
                AVG(CAST(f.has_explained_keyword AS INT))    AS explained,
                AVG(CAST(f.has_ranking_keyword AS INT))      AS ranking,
                AVG(CAST(f.has_curiosity_keyword AS INT))    AS curiosity,
                AVG(CAST(f.has_extreme_adjective AS INT))    AS extreme,
                AVG(f.caps_ratio)                            AS caps_ratio,
                AVG(f.char_len)                              AS char_len
            FROM videos v JOIN video_features f ON f.video_id = v.id
            WHERE v.channel_id = ? AND v.is_short = false
        ),
        niche_stats AS (
            SELECT
                AVG(CAST(f.has_caps_word AS INT))            AS caps_word,
                AVG(CAST(f.has_number AS INT))               AS number,
                AVG(CAST(f.has_question_mark AS INT))        AS question,
                AVG(CAST(f.has_emoji AS INT))                AS emoji,
                AVG(CAST(f.has_first_person AS INT))         AS first_person,
                AVG(CAST(f.has_explained_keyword AS INT))    AS explained,
                AVG(CAST(f.has_ranking_keyword AS INT))      AS ranking,
                AVG(CAST(f.has_curiosity_keyword AS INT))    AS curiosity,
                AVG(CAST(f.has_extreme_adjective AS INT))    AS extreme,
                AVG(f.caps_ratio)                            AS caps_ratio,
                AVG(f.char_len)                              AS char_len
            FROM videos v
            JOIN video_features f ON f.video_id = v.id
            JOIN outliers o ON o.video_id = v.id
            WHERE v.is_short = false AND o.percentile_in_channel >= 90
              AND v.channel_id != ?
        )
        SELECT * FROM own_stats UNION ALL SELECT * FROM niche_stats
        """,
        [own, own],
    ).df()

    if gap.shape[0] == 2:
        own_row = gap.iloc[0]
        niche_row = gap.iloc[1]
        rows: list[dict] = []
        rate_features = [
            ("caps_word", "tem palavra em CAPS"),
            ("number", "tem número"),
            ("question", "tem ?"),
            ("emoji", "tem emoji"),
            ("first_person", "1ª pessoa (eu/meu)"),
            ("explained", "EXPLICADO/ENTENDA"),
            ("ranking", "TOP/RANKING"),
            ("curiosity", "curiosity gap"),
            ("extreme", "adjetivo extremo"),
        ]
        for key, label in rate_features:
            o = float(own_row[key]) * 100 if pd.notna(own_row[key]) else 0
            n = float(niche_row[key]) * 100 if pd.notna(niche_row[key]) else 0
            rows.append({
                "feature": label,
                "você %": round(o, 1),
                "nicho outliers %": round(n, 1),
                "diff (pp)": round(o - n, 1),
            })
        for key, label, fmt in [
            ("caps_ratio", "caps_ratio (média)", "{:.2f}"),
            ("char_len", "comprimento (chars)", "{:.0f}"),
        ]:
            o_v = float(own_row[key]) if pd.notna(own_row[key]) else 0
            n_v = float(niche_row[key]) if pd.notna(niche_row[key]) else 0
            rows.append({
                "feature": label,
                "você %": fmt.format(o_v),
                "nicho outliers %": fmt.format(n_v),
                "diff (pp)": fmt.format(o_v - n_v),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("Sem dados de comparação (canais vizinhos sem outliers).")

    st.markdown("---")

    # Themes covered + their multiplier vs niche
    st.subheader("Temas cobertos vs nicho")
    st.caption(
        "Quais temas (BERTopic Camada A) seus vídeos tocaram, "
        "teu multiplier médio nesse tema e o do nicho."
    )
    themes = con.execute(
        """
        WITH own_themes AS (
            SELECT f.theme_label, COUNT(*) AS own_n,
                   AVG(o.multiplier) AS own_avg_mult,
                   MAX(o.multiplier) AS own_top_mult
            FROM videos v
            JOIN video_features f ON f.video_id = v.id
            LEFT JOIN outliers o ON o.video_id = v.id
            WHERE v.channel_id = ? AND v.is_short = false AND f.theme_label IS NOT NULL
            GROUP BY 1
        ),
        niche_themes AS (
            SELECT f.theme_label, COUNT(*) AS niche_n,
                   AVG(o.multiplier) AS niche_avg_mult,
                   MAX(o.multiplier) AS niche_top_mult
            FROM videos v
            JOIN video_features f ON f.video_id = v.id
            LEFT JOIN outliers o ON o.video_id = v.id
            WHERE v.channel_id != ? AND v.is_short = false AND f.theme_label IS NOT NULL
            GROUP BY 1
        )
        SELECT o.theme_label,
               o.own_n, ROUND(o.own_avg_mult, 2) AS own_avg, ROUND(o.own_top_mult, 1) AS own_top,
               n.niche_n, ROUND(n.niche_avg_mult, 2) AS niche_avg, ROUND(n.niche_top_mult, 1) AS niche_top
        FROM own_themes o
        LEFT JOIN niche_themes n USING (theme_label)
        ORDER BY o.own_avg_mult DESC NULLS LAST
        LIMIT 30
        """,
        [own, own],
    ).df()
    if themes.empty:
        st.info("Sem temas detectados nos teus vídeos. Rode `jason features topics`.")
    else:
        st.dataframe(themes, hide_index=True, use_container_width=True)

    st.markdown("---")

    # Views over time
    st.subheader("Views ao longo do tempo")
    df = con.execute(
        """
        SELECT v.published_at, v.title, latest.views
        FROM videos v
        JOIN (
            SELECT video_id, MAX(views) AS views
            FROM video_stats_snapshots GROUP BY video_id
        ) latest ON latest.video_id = v.id
        WHERE v.channel_id = ? AND v.is_short = false
        ORDER BY v.published_at
        """,
        [own],
    ).df()
    st.line_chart(df, x="published_at", y="views")


def _tab_title_scorer() -> None:
    st.header("Title scorer")
    st.caption("Score de um título candidato pelo regressor da Fase 3.")

    settings = get_settings()
    title = st.text_input("Título candidato", "FINAL EXPLICADO de Hereditário (2018)")
    channel = st.text_input("Channel ID (UC...)", settings.own_channel_id)
    duration_min = st.number_input(
        "Duração estimada (minutos)", min_value=1.0, max_value=180.0, value=40.0, step=1.0,
        help="O canal foca em análises longas (~30–50 min). Convertido pra segundos antes do score.",
    )
    duration_s = int(duration_min * 60)
    st.caption(f"= {duration_s}s")

    if st.button("Score"):
        try:
            from jason.models.predict import score_title_with_explanation
            r = score_title_with_explanation(
                title, channel, duration_s=duration_s, top_k=8,
            )
            c1, c2 = st.columns([1, 2])
            with c1:
                st.metric("Multiplier predito", f"{r['multiplier']:.2f}x")
                st.caption(f"log_multiplier = {r['log_multiplier']:.4f}")
                st.caption(f"base value = {r['base_value']:.3f}")
            with c2:
                st.markdown("**Por que esse score?**")
                st.caption(
                    "Contribuição de cada feature pra log_multiplier "
                    "(SHAP-like via LightGBM). Verde = empurrou pra cima, vermelho = pra baixo."
                )
                for c in r["contributions"]:
                    color = "#5BC076" if c["direction"] == "up" else "#B11C19"
                    arrow = "▲" if c["direction"] == "up" else "▼"
                    st.markdown(
                        f"<div style='display:flex;gap:0.6rem;align-items:center;"
                        f"padding:0.25rem 0;border-bottom:1px solid #2A2A2A'>"
                        f"<div style='color:{color};font-family:JetBrains Mono;width:5rem'>"
                        f"{arrow} {c['contribution']:+.3f}</div>"
                        f"<div style='font-family:JetBrains Mono;color:#E8E5DE;flex:1'>"
                        f"{c['feature']}</div>"
                        f"<div style='color:#888880;font-family:JetBrains Mono'>"
                        f"= {c['value']}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        except FileNotFoundError as exc:
            st.error(f"{exc}\n\nRode `jason model train` primeiro.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Erro: {exc}")


def _tab_suggest_title() -> None:
    st.header("Sugerir título")
    st.caption("RAG sobre outliers do nicho · Claude (com prompt caching) · ranqueia top-3.")

    settings = get_settings()
    transcript = st.text_area(
        "Transcrição/resumo", height=200, placeholder="O filme aborda...",
    )
    channel = st.text_input("Channel ID", settings.own_channel_id, key="suggest_channel")
    theme = st.text_input("Tema/franquia (opcional)", "")
    num = st.slider("Quantos candidatos gerar", 3, 15, 10)
    duration_min = st.number_input(
        "Duração estimada (minutos)", min_value=1.0, max_value=180.0, value=40.0, step=1.0,
        help="Duração tem peso alto no modelo (#2 feature). Convertido pra segundos antes do score.",
        key="suggest_duration_min",
    )
    duration = int(duration_min * 60)
    st.caption(f"= {duration}s")

    if st.button("Gerar"):
        if not transcript.strip():
            st.warning("Cola um texto primeiro.")
            return
        try:
            from jason.generation.titles import generate_titles
            with st.spinner("Chamando Claude..."):
                result = generate_titles(
                    transcript, channel_id=channel,
                    theme=theme or None, num_candidates=num,
                )
            try:
                from jason.models.predict import score_title_with_explanation
                scored = []
                for t in result["titles"]:
                    s = score_title_with_explanation(
                        t, channel, duration_s=int(duration), top_k=4,
                    )
                    scored.append((t, s["multiplier"], s["contributions"]))
                scored.sort(key=lambda x: x[1], reverse=True)
            except FileNotFoundError:
                scored = [(t, None, None) for t in result["titles"]]
                st.info("Modelo ainda não treinado — exibindo sem score.")

            st.subheader("Candidatos")
            for i, item in enumerate(scored, start=1):
                t, mult, contribs = item
                pill = _multiplier_pill(mult) if mult else _pill("—")
                with st.container():
                    st.markdown(
                        f"<div style='display:flex;gap:0.8rem;align-items:center;"
                        f"padding:0.6rem 0 0.3rem 0'>"
                        f"<div style='font-family:JetBrains Mono;color:#888880;width:1.5rem'>{i:02d}</div>"
                        f"<div>{pill}</div>"
                        f"<div style='flex:1;font-size:1rem'>{t}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    if contribs:
                        with st.expander("por quê?"):
                            for c in contribs:
                                color = "#5BC076" if c["direction"] == "up" else "#B11C19"
                                arrow = "▲" if c["direction"] == "up" else "▼"
                                st.markdown(
                                    f"<div style='display:flex;gap:0.6rem;"
                                    f"font-family:JetBrains Mono;font-size:0.82rem;"
                                    f"padding:0.15rem 0'>"
                                    f"<span style='color:{color};width:5rem'>"
                                    f"{arrow} {c['contribution']:+.3f}</span>"
                                    f"<span style='flex:1'>{c['feature']}</span>"
                                    f"<span style='color:#888880'>= {c['value']}</span>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                    st.markdown(
                        "<hr style='margin:0.4rem 0;border-color:#1F1F1F'>",
                        unsafe_allow_html=True,
                    )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Erro: {exc}")


def _tab_suggest_thumb() -> None:
    st.header("Sugerir thumbnail")
    st.caption("Frame extraction + score combinado vs centroide outlier do nicho.")

    st.markdown("""
**Pipeline**
1. ffmpeg extrai 20 frames espaçados em 5–95% da duração
2. Filtra dark/blurry (luminância + variância de Laplaciano)
3. Score combinado: `0.4 * face_score (Haar) + 0.6 * cosine vs centroide outlier thumbs`
4. Salva top-3 frames + `overlay_suggestion.json`

**Como rodar**
```
jason thumbs suggest --video-path video.mp4 --top-k 3 [--theme-id N]
```

**Output em** `data/thumb_suggestions/<video>/`:
- `frame_*.jpg` — top-3 candidatos
- `overlay_suggestion.json` — texto sugerido, posição, cor, exemplos do nicho

**Workflow real**: a thumb final é editada por você (Photoshop/Canva). JASON
escolhe o frame base + diz onde colocar o overlay. Não tenta gerar a thumb
finalizada (escopo explode com qualidade inconsistente).
    """)

    st.markdown("---")
    st.subheader("Padrões de thumbnail por tema (referência)")
    st.caption(
        "Pra cada tema do BERTopic, exemplos de thumbs que viraram outlier (p≥90) — "
        "usa como referência visual quando estiver editando a tua."
    )

    con = _con()
    themes = con.execute(
        """
        SELECT f.theme_label, COUNT(*) AS n_outliers
        FROM videos v
        JOIN video_features f ON f.video_id = v.id
        JOIN outliers o ON o.video_id = v.id
        WHERE v.is_short = false AND o.percentile_in_channel >= 90 AND f.theme_label IS NOT NULL
        GROUP BY 1
        HAVING COUNT(*) >= 3
        ORDER BY n_outliers DESC
        LIMIT 30
        """,
    ).df()
    if themes.empty:
        st.info("Sem outliers por tema ainda. Rode `jason features outliers --live`.")
        return

    theme_choice = st.selectbox(
        "Tema",
        ["(escolha)"] + [f"{r['theme_label']} ({r['n_outliers']} outliers)" for _, r in themes.iterrows()],
    )
    if theme_choice == "(escolha)":
        return

    label = theme_choice.split(" (")[0]
    samples = con.execute(
        """
        SELECT v.id, v.title, c.title AS channel, v.thumbnail_url, o.multiplier
        FROM videos v
        JOIN channels c ON c.id = v.channel_id
        JOIN video_features f ON f.video_id = v.id
        JOIN outliers o ON o.video_id = v.id
        WHERE f.theme_label = ? AND o.percentile_in_channel >= 90
        ORDER BY o.multiplier DESC
        LIMIT 9
        """,
        [label],
    ).df()

    # Try to compute dominant colors across local thumbnail files for this theme.
    # Falls back silently if PIL/sklearn not installed or no local files yet.
    settings = get_settings()
    thumb_dir = settings.data_dir / "thumbnails"
    local_paths = []
    for _, r in samples.iterrows():
        p = thumb_dir / f"{r['id']}.jpg"
        if p.exists():
            local_paths.append(p)
    if len(local_paths) >= 3:
        try:
            from jason.thumbs.colors import dominant_colors_from_paths, hex_from_rgb
            colors = dominant_colors_from_paths(local_paths, k=4)
            if colors:
                st.markdown("**Paleta dominante do tema**")
                st.caption(
                    "4 cores principais extraídas via k-means sobre os pixels "
                    "das thumbs outliers desse tema. Use como referência quando "
                    "editar tua thumb (mesmo background tone, accent, etc)."
                )
                swatches = "".join(
                    f"<div style='display:inline-block;margin-right:0.4rem;text-align:center'>"
                    f"<div style='width:80px;height:60px;background:{hex_from_rgb(c)};"
                    f"border:1px solid #2A2A2A'></div>"
                    f"<div style='font-family:JetBrains Mono;font-size:0.7rem;"
                    f"color:#888880;margin-top:0.2rem'>{hex_from_rgb(c)}</div>"
                    f"</div>"
                    for c in colors
                )
                st.markdown(swatches, unsafe_allow_html=True)
                st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)
        except (ImportError, ModuleNotFoundError):
            pass  # ML group not installed — skip palette silently

    cols = st.columns(3)
    for i, (_, row) in enumerate(samples.iterrows()):
        with cols[i % 3]:
            if row.get("thumbnail_url"):
                st.image(row["thumbnail_url"], use_container_width=True)
            st.caption(
                f"{_multiplier_pill(row['multiplier'])} "
                f"<span style='color:#888880'>[{row['channel']}]</span><br>"
                f"<span style='font-size:0.85rem'>{row['title'][:80]}</span>",
            )
            st.markdown(
                f"<div style='font-family:JetBrains Mono;font-size:0.75rem;color:#888880'>"
                f"<a href='https://youtu.be/{row['id']}'>↗ youtube</a></div>",
                unsafe_allow_html=True,
            )


def _tab_ab_test_log() -> None:
    """Fase 6 — formulário pra inserir resultados do Test & Compare nativo do YouTube."""
    st.header("A/B feedback (Test & Compare)")
    st.caption(
        "Insira aqui o resultado do A/B test nativo do YouTube depois "
        "que ele fechar (5–7 dias). Esses sinais entram no retreino."
    )

    settings = get_settings()
    con = _con()

    with st.form("ab_test_form"):
        video_id = st.text_input("Video ID (11 chars)", placeholder="dQw4w9WgXcQ")
        col1, col2 = st.columns(2)
        title_a = col1.text_input("Variante A — título")
        title_b = col2.text_input("Variante B — título")
        wts_a = col1.number_input(
            "A — watch_time_share (0..1)", min_value=0.0, max_value=1.0, value=0.5, step=0.01,
        )
        wts_b = col2.number_input(
            "B — watch_time_share (0..1)", min_value=0.0, max_value=1.0, value=0.5, step=0.01,
        )
        result_kind = st.radio(
            "Resultado", ["winner_loser", "inconclusive"], horizontal=True,
        )
        winner_variant = st.radio("Vencedor (se houver)", ["A", "B"], horizontal=True)
        confidence = st.number_input("Confidence (%)", min_value=0.0, max_value=100.0, value=80.0)
        submitted = st.form_submit_button("Salvar")

    if submitted:
        if not video_id or not title_a or not title_b:
            st.error("Preencha video_id e os dois títulos.")
            return
        with duckdb.connect(str(settings.duckdb_path)) as wcon:
            if result_kind == "inconclusive":
                results = [("inconclusive", title_a, 1), ("inconclusive", title_b, 2)]
            elif winner_variant == "A":
                results = [("winner", title_a, 1), ("loser", title_b, 2)]
            else:
                results = [("loser", title_a, 1), ("winner", title_b, 2)]
            wts = {1: wts_a, 2: wts_b}
            for r, title, vid_var in results:
                wcon.execute(
                    """
                    INSERT INTO title_tests
                        (video_id, variant_id, title, watch_time_share, result, confidence_pct)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (video_id, variant_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        watch_time_share = EXCLUDED.watch_time_share,
                        result = EXCLUDED.result,
                        confidence_pct = EXCLUDED.confidence_pct
                    """,
                    [video_id, vid_var, title, wts[vid_var], r, confidence],
                )
        st.success(f"Salvos {len(results)} variantes para {video_id}.")
        _con.clear()

    st.subheader("Tests registrados")
    df = con.execute(
        "SELECT video_id, variant_id, title, result, confidence_pct, recorded_at "
        "FROM title_tests ORDER BY recorded_at DESC LIMIT 50",
    ).df()
    if df.empty:
        st.info("Nenhum test registrado ainda.")
    else:
        st.dataframe(df, hide_index=True, use_container_width=True)


# --- main ----------------------------------------------------------------

tabs = st.tabs([
    "Outliers", "Próprio", "Score", "Sugerir título",
    "Sugerir thumb", "A/B feedback",
])
with tabs[0]:
    _tab_outliers()
with tabs[1]:
    _tab_own_performance()
with tabs[2]:
    _tab_title_scorer()
with tabs[3]:
    _tab_suggest_title()
with tabs[4]:
    _tab_suggest_thumb()
with tabs[5]:
    _tab_ab_test_log()
