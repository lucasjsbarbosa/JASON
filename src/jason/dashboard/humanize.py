"""Tradução de features/valores do modelo pra linguagem natural PT-BR.

O modelo trabalha em jargão (`has_explained_keyword`, `caps_ratio`,
`days_to_nearest_horror_release`, `title_cluster`, etc). A criadora não
precisa nem deve ler isso — ela quer saber "por que esse título foi
melhor que aquele" em português normal.

Este módulo é a única fonte de verdade pras strings exibidas na UI.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Mapeamento de feature técnica -> rótulo humano em PT-BR.
# Mantém terminologia do nicho (CAPS, packaging, etc) — mas sem jargão de ML.
FEATURE_LABELS: dict[str, str] = {
    # Title features
    "has_explained_keyword":   "Título tem 'EXPLICADO' ou 'ENTENDA'",
    "has_ranking_keyword":     "Título é ranking (TOP, MELHORES, PIORES)",
    "has_curiosity_keyword":   "Título tem curiosity gap (POR QUE, NÃO SABIAM)",
    "has_extreme_adjective":   "Título tem adjetivo extremo (PERTURBADOR, INSANO)",
    "has_caps_word":           "Título tem palavra em CAPS",
    "has_number":              "Título tem número (Top 10, 7 razões…)",
    "has_emoji":               "Título tem emoji",
    "has_question_mark":       "Título tem ?",
    "has_first_person":        "Título usa 1ª pessoa (eu, meu, minha)",
    "caps_ratio":              "% do título em CAPS",
    "char_len":                "Tamanho do título (caracteres)",
    "word_count":              "Quantidade de palavras",
    "sentiment_score":         "Sentimento do título",
    # Video / channel
    "duration_s":              "Duração do vídeo",
    "subs_bucket":             "Tamanho do canal (faixa de inscritos)",
    # Calendar
    "published_hour":          "Hora da publicação",
    "published_dow":           "Dia da semana da publicação",
    "is_halloween_week":       "Publicado na semana do Halloween",
    "is_friday_13_week":       "Publicado em semana de Sexta 13",
    "days_to_nearest_horror_release": "Proximidade do lançamento grande de terror mais próximo",
    # Topic / cluster
    "theme_id":                "Subgênero detectado (BERTopic)",
    "theme_label":             "Subgênero detectado",
    "franchise_id":            "Franquia detectada",
    "franchise_label":         "Franquia detectada",
    "title_cluster":           "Estilo de título parecido com outros que viralizaram",
    "thumb_cluster":           "Estilo visual de thumb parecido com outros outliers",
}

# Quando o valor é booleano-ish, traduz pra sim/não no contexto.
_BOOL_TRUE = {"True", "true", "1"}
_BOOL_FALSE = {"False", "false", "0"}


def humanize_value(feature: str, raw_value: Any) -> str:
    """Traduz um valor de feature pra string que faz sentido pra um humano."""
    s = str(raw_value)

    if pd.isna(raw_value) if not isinstance(raw_value, str) else False:
        return "—"

    # Booleans pra has_*
    if feature.startswith("has_") or feature.startswith("is_"):
        if s in _BOOL_TRUE:
            return "sim"
        if s in _BOOL_FALSE:
            return "não"

    # caps_ratio é fração 0..1 — mostra como %
    if feature == "caps_ratio":
        try:
            return f"{float(s) * 100:.0f}%"
        except (TypeError, ValueError):
            return s

    if feature == "duration_s":
        try:
            sec = int(float(s))
            mins = sec // 60
            return f"{mins} min"
        except (TypeError, ValueError):
            return s

    if feature == "published_hour":
        # Modelo treinou em UTC (todos os 25 canais são BR — shift constante
        # de -3h faz o modelo aprender o mesmo padrão). Display converte pra
        # BRT pra ficar legível.
        try:
            utc_h = int(float(s))
            brt_h = (utc_h - 3) % 24
            return f"{brt_h:02d}h"
        except (TypeError, ValueError):
            return s

    if feature == "published_dow":
        # Idem: dow em UTC é o que o modelo viu. Pra exibir, se a hora UTC
        # estiver em [0, 2] o dia local é o anterior — mas como o display
        # do dow não tem acesso ao hour aqui, mantemos o dow UTC (erro de
        # ~1/8 dos casos só pra uploads madrugada). Aceito por simplicidade.
        try:
            i = int(float(s))
            return ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"][i] if 0 <= i <= 6 else s
        except (TypeError, ValueError):
            return s

    if feature == "subs_bucket":
        try:
            i = int(float(s))
            tiers = {
                0: "muito pequeno (até 1k)",
                1: "pequeno (1k–10k)",
                2: "médio (10k–100k)",
                3: "grande (100k–1M)",
                4: "muito grande (1M+)",
            }
            return tiers.get(i, s)
        except (TypeError, ValueError):
            return s

    if feature == "days_to_nearest_horror_release":
        try:
            d = int(float(s))
            if d == 0:
                return "no mesmo dia"
            if abs(d) <= 3:
                return f"{abs(d)} dia{'s' if abs(d) > 1 else ''}"
            if abs(d) <= 30:
                return f"~{abs(d)} dias"
            return f"{abs(d)} dias (longe)"
        except (TypeError, ValueError):
            return s

    # cluster IDs são abstrações — esconde o número, mostra só "tipo N"
    if feature in ("title_cluster", "thumb_cluster", "theme_id", "franchise_id"):
        return f"tipo #{s}" if s and s not in ("nan", "None", "—", "-1") else "—"

    # char_len, word_count: número direto
    return s


# Direção da contribuição em PT-BR — substitui "up/down" técnico.
def humanize_direction(direction: str, contribution: float) -> tuple[str, str]:
    """Returns (verb, color_hex). verb é o que essa feature fez ao score."""
    if direction == "up":
        return "ajudou", "#5BC076"
    return "atrapalhou", "#B11C19"


def humanize_contribution(c: dict[str, Any]) -> dict[str, str]:
    """Mapeia um contribution dict do score_title_with_explanation pra
    versão pronta pra UI: label PT-BR + valor humano + texto de impacto."""
    feature = c["feature"]
    label = FEATURE_LABELS.get(feature, feature.replace("_", " "))
    value = humanize_value(feature, c["value"])
    verb, color = humanize_direction(c["direction"], c["contribution"])
    return {
        "label": label,
        "value": value,
        "verb": verb,
        "color": color,
        "magnitude": abs(c["contribution"]),
    }


def humanize_multiplier(mult: float) -> str:
    """Texto curto sobre o que o multiplier significa pra um humano."""
    if mult >= 5.0:
        return f"bombou {mult:.1f}x — outlier forte"
    if mult >= 2.0:
        return f"{mult:.1f}x acima da média do canal"
    if mult >= 1.2:
        return f"{mult:.1f}x — um pouco acima"
    if mult >= 0.8:
        return f"{mult:.1f}x — perto da média"
    return f"{mult:.1f}x — abaixo da média"


def humanize_percentile(pct: float) -> str:
    """p90+ é outlier oficial. Traduz."""
    if pct >= 99:
        return "topo absoluto do canal"
    if pct >= 95:
        return "top 5% do canal"
    if pct >= 90:
        return "top 10% do canal"
    if pct >= 75:
        return "acima da média do canal"
    if pct >= 50:
        return "perto da mediana"
    return "abaixo da mediana"


_LABEL_STOPWORDS = {
    "um", "uma", "de", "do", "da", "dos", "das", "o", "a", "os", "as",
    "para", "com", "e", "ou", "mais", "menos", "muito", "que", "se",
    "no", "na", "nos", "nas", "em", "por", "ao", "aos", "à", "às",
    "the", "of", "and", "or", "to", "in", "on", "at", "is", "are",
    "sem", "ja", "também", "tambem",
}


def humanize_topic_label(label: str | None) -> str | None:
    """Limpa labels do BERTopic do tipo `4_terror_pesadelo_assustador_um`
    pra `Terror · Pesadelo · Assustador`. Filtra stopwords + número topic id.

    Retorna None quando o label não tem informação (vazio, '-1', etc) — caller
    decide se mostra ou esconde.
    """
    if not label:
        return None
    s = str(label).strip()
    if s.lower() in ("nan", "none", "-1", ""):
        return None
    parts = s.split("_")
    # Strip leading numeric topic id
    if parts and parts[0].isdigit():
        parts = parts[1:]
    parts = [p for p in parts if p.lower() not in _LABEL_STOPWORDS and len(p) > 1]
    if not parts:
        return None
    # Pega no máximo 3 termos significativos
    parts = parts[:3]
    return " · ".join(p.capitalize() for p in parts)
