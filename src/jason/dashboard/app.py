"""JASON dashboard — Streamlit, 5 abas (Fase 5).

Run with: `uv run streamlit run src/jason/dashboard/app.py`

Each tab gracefully degrades when its data dependency isn't ready yet
(e.g. no outliers populated, no model artifact). The point is to be
useful from day 1 even before all the ML pieces have produced output.
"""

from __future__ import annotations

import duckdb
import streamlit as st

from jason.config import get_settings

st.set_page_config(page_title="JASON", page_icon="🔪", layout="wide")
st.title("🔪 JASON — YouTube growth engine")
st.caption("They call him JSON. He parses your YouTube data and won't stop until your CTR is dead.")


@st.cache_resource
def _con() -> duckdb.DuckDBPyConnection:
    settings = get_settings()
    return duckdb.connect(str(settings.duckdb_path), read_only=True)


def _tab_outliers() -> None:
    st.header("Outliers do nicho")
    st.caption("Ranqueado por `percentile_in_channel` (90+ é outlier oficial). "
               "Quando vazio, ainda não há ~28 dias de snapshot — usa fallback de top views.")

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
    if has_pct:
        sql += " ORDER BY pct DESC, mult DESC LIMIT 50"
    else:
        sql += " ORDER BY latest.views DESC LIMIT 50"

    df = con.execute(sql, params).df()
    if df.empty:
        st.info("Sem vídeos no DB ainda. Rode `jason ingest channels`.")
        return

    if not has_pct:
        st.warning(
            "`outliers.percentile_in_channel` ainda vazio — exibindo por views. "
            "Rode `jason snapshot run` semanalmente; em ~28 dias o multiplier materializa."
        )

    for _, row in df.head(20).iterrows():
        cols = st.columns([1, 4])
        with cols[0]:
            if row.get("thumbnail_url"):
                st.image(row["thumbnail_url"], width=160)
        with cols[1]:
            st.markdown(f"**[{row['channel']}]** {row['title']}")
            meta = []
            if row["pct"]:
                meta.append(f"p{row['pct']:.0f}")
            if row["mult"]:
                meta.append(f"{row['mult']:.1f}×")
            if row["views"]:
                meta.append(f"{int(row['views']):,} views")
            if row.get("theme_label"):
                meta.append(f"theme: {row['theme_label']}")
            if row.get("franchise_label"):
                meta.append(f"franchise: {row['franchise_label']}")
            st.caption(" · ".join(meta))
            st.markdown(f"[abrir no YouTube](https://youtu.be/{row['id']})")


def _tab_own_performance() -> None:
    st.header("Performance própria (@babygiulybaby)")
    st.caption("CTR / AVD / retention exigem OAuth do YouTube Analytics — "
               "hoje mostro só views ao longo do tempo (Data API pública). "
               "Sobreposição: lançamentos de horror (TMDb).")

    settings = get_settings()
    own = settings.own_channel_id
    con = _con()

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
    if df.empty:
        st.info(f"Canal próprio ({own}) não tem dados ainda. Rode "
                "`jason ingest channels --ids {own}`.")
        return

    st.line_chart(df, x="published_at", y="views")
    st.dataframe(df.tail(10)[["published_at", "title", "views"]])


def _tab_title_scorer() -> None:
    st.header("Title scorer")
    st.caption("Score de um título candidato pelo regressor da Fase 3.")

    settings = get_settings()
    title = st.text_input("Título candidato", "FINAL EXPLICADO de Hereditário (2018)")
    channel = st.text_input("Channel ID (UC...)", settings.own_channel_id)
    duration = st.number_input("Duração estimada (s)", min_value=60, value=600)

    if st.button("Score"):
        try:
            from jason.models.predict import score_title
            r = score_title(title, channel, duration_s=duration)
            st.metric("Multiplier predito", f"{r['multiplier']:.2f}×")
            st.caption(f"log_multiplier = {r['log_multiplier']:.4f}")
        except FileNotFoundError as exc:
            st.error(f"{exc}\n\nRode `jason model train` primeiro.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Erro: {exc}")


def _tab_suggest_title() -> None:
    st.header("Sugerir título (RAG + Claude + score)")
    st.caption("Cola um resumo / transcrição. JASON gera 10 candidatos via "
               "Claude (com prompt caching), ranqueia pelo modelo e devolve top-3.")

    settings = get_settings()
    transcript = st.text_area("Transcrição/resumo", height=200,
                              placeholder="O filme aborda...")
    channel = st.text_input("Channel ID", settings.own_channel_id, key="suggest_channel")
    theme = st.text_input("Tema/franquia (opcional)", "")
    num = st.slider("Quantos candidatos gerar", 3, 15, 10)

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
                from jason.models.predict import score_title
                scored = [(t, score_title(t, channel)["multiplier"]) for t in result["titles"]]
                scored.sort(key=lambda x: x[1], reverse=True)
            except FileNotFoundError:
                scored = [(t, None) for t in result["titles"]]
                st.info("Modelo ainda não treinado — exibindo sem score.")

            st.subheader("Candidatos")
            for i, (t, mult) in enumerate(scored, start=1):
                col1, col2 = st.columns([1, 6])
                col1.markdown(f"**{i}.**" + (f" {mult:.2f}×" if mult else ""))
                col2.write(t)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Erro: {exc}")


def _tab_suggest_thumb() -> None:
    st.header("Sugerir thumbnail")
    st.caption("Fase 4.5 — pendente. Seleção de frames via ffmpeg + scoring "
               "vs centroides de outliers do mesmo theme_id.")
    st.info("Esta aba será ativada quando `jason thumbs suggest` for implementado.")


# --- main ------------------------------------------------------------------

tabs = st.tabs([
    "📈 Outliers", "👤 Próprio", "🎯 Score", "✍️ Sugerir título", "🖼 Sugerir thumb",
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
