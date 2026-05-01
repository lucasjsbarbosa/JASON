"use client";

import { useEffect, useState } from "react";
import {
  api,
  type PowerKeyword,
  type ThemeKeywords,
  type ThemeOption,
} from "@/lib/api";

export default function PalavrasPage() {
  const [themes, setThemes] = useState<ThemeOption[]>([]);
  const [themeId, setThemeId] = useState<number | null>(null);
  const [keywords, setKeywords] = useState<PowerKeyword[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<ThemeOption[]>("/api/themes")
      .then((r) => {
        setThemes(r);
        if (r.length > 0 && themeId === null) setThemeId(r[0].id);
      })
      .catch((e) => setError((e as Error).message));
  }, [themeId]);

  useEffect(() => {
    if (themeId === null) return;
    setLoading(true);
    setError(null);
    api<ThemeKeywords>(`/api/themes/${themeId}/keywords?top_k=30`)
      .then((r) => setKeywords(r.keywords))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [themeId]);

  return (
    <div className="space-y-8 max-w-5xl">
      <section>
        <h1 className="text-2xl">Palavras que bombam</h1>
        <p className="text-sm text-[var(--muted)] mt-2 max-w-3xl">
          Palavras e expressões que aparecem com mais frequência nos vídeos
          vencedores de cada subgênero (top 10% do canal), comparado com o
          que é normal no mesmo subgênero. O que está em primeiro lugar é o
          que mais separa um vídeo que bombou de um vídeo comum.
        </p>
      </section>

      <section className="card">
        <label className="block text-xs uppercase tracking-wider mb-2 text-[var(--muted)]">
          Subgênero
        </label>
        <select
          value={themeId ?? ""}
          onChange={(e) => setThemeId(Number(e.target.value))}
          className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm focus:outline-none focus:border-[var(--accent)]"
        >
          {themes.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label} · {t.n_outliers} vídeos vencedores
            </option>
          ))}
        </select>
      </section>

      {error && (
        <div className="card border-[var(--accent)] text-[var(--accent)] text-sm">
          {error}
        </div>
      )}

      {loading && (
        <div className="text-sm text-[var(--muted)]">Carregando…</div>
      )}

      {!loading && keywords.length === 0 && themeId !== null && !error && (
        <div className="card text-sm text-[var(--muted)]">
          Sem palavras suficientes pra esse subgênero. Tente outro.
        </div>
      )}

      {keywords.length > 0 && (
        <section className="card">
          <h2 className="text-sm uppercase tracking-wider text-[var(--muted)] mb-4">
            Top expressões deste subgênero
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="text-left py-2 font-mono text-xs text-[var(--muted)]">
                  expressão
                </th>
                <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                  vencedores
                </th>
                <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                  comuns
                </th>
                <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                  força do sinal
                </th>
              </tr>
            </thead>
            <tbody>
              {keywords.map((k) => {
                const strength = Math.min(100, Math.round(k.z_score * 10));
                return (
                  <tr
                    key={k.ngram}
                    className="border-b border-[var(--border)]/50"
                  >
                    <td className="py-2 font-mono uppercase tracking-wide">
                      {k.ngram}
                    </td>
                    <td className="text-right tabular-nums">
                      {k.outlier_count}
                    </td>
                    <td className="text-right tabular-nums text-[var(--muted)]">
                      {k.baseline_count}
                    </td>
                    <td className="text-right tabular-nums">
                      <span
                        className="pill"
                        style={{
                          background: `color-mix(in oklch, var(--accent) ${strength}%, transparent)`,
                        }}
                      >
                        {k.z_score.toFixed(1)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="text-xs text-[var(--muted)] mt-4 max-w-2xl">
            "Vencedores" = quantos vídeos top-10% do subgênero usam a
            expressão. "Comuns" = quantos vídeos comuns também usam. "Força do
            sinal" cresce quando a expressão aparece muito mais em vencedores
            que em comuns, levando em conta o tamanho dos dois grupos.
          </p>
        </section>
      )}
    </div>
  );
}
