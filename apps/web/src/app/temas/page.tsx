"use client";

import { useEffect, useState } from "react";
import { api, type ThemeSuggestion } from "@/lib/api";

function blocks(v: number) {
  // Monospaced 10-block indicator: ▮▮▮▮▮▯▯▯▯▯ — gives axis (0..10),
  // brutalist tone, doesn't read as a SaaS dashboard bar.
  const filled = Math.round(Math.max(0, Math.min(1, v)) * 10);
  return "▮".repeat(filled) + "▯".repeat(10 - filled);
}

export default function TemasPage() {
  const [items, setItems] = useState<ThemeSuggestion[]>([]);
  const [horizon, setHorizon] = useState(60);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api<ThemeSuggestion[]>(`/api/sugerir-tema?top_k=10&horizon_days=${horizon}`)
      .then(setItems)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [horizon]);

  return (
    <div className="space-y-8 max-w-5xl">
      <section>
        <h1 className="text-2xl">Sugerir tema</h1>
        <p className="text-sm text-[var(--muted)] mt-2 max-w-3xl">
          Subgêneros que valem a pena cobrir agora, ordenados por uma soma
          de quatro sinais: lançamentos de cinema/streaming próximos, tema
          esquentando vs esfriando no nicho, quantos vizinhos estão batendo
          nele, e se você ainda não bateu top-10% nele.
        </p>
      </section>

      <section className="card flex items-end gap-4">
        <div>
          <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
            Olhar lançamentos dos próximos
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={horizon}
              min={7}
              max={365}
              onChange={(e) => setHorizon(Number(e.target.value))}
              className="bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm w-24 focus:outline-none focus:border-[var(--accent)]"
            />
            <span className="text-sm text-[var(--muted)]">dias</span>
          </div>
        </div>
      </section>

      {error && (
        <div className="card border-[var(--accent)] text-[var(--accent)] text-sm">
          {error}
        </div>
      )}

      {loading && <div className="text-sm text-[var(--muted)]">Carregando…</div>}

      <section className="space-y-4">
        {items.map((t, i) => (
          <div key={t.theme_id} className="card">
            <div className="flex items-baseline justify-between">
              <div>
                <div className="text-xs uppercase tracking-wider text-[var(--muted)]">
                  #{i + 1}
                </div>
                <div className="text-lg mt-1">
                  {t.label_human ?? t.label ?? `tema ${t.theme_id}`}
                </div>
              </div>
              <div
                className="font-mono text-xs tabular-nums text-[var(--muted)] uppercase tracking-wider"
                title="Soma ponderada dos 4 sinais abaixo"
              >
                força
                <br />
                <span
                  className="text-base"
                  style={{ color: "var(--text)", letterSpacing: "0" }}
                >
                  {blocks(t.score_total)}
                </span>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3 font-mono text-xs">
              <div className="flex items-center gap-3">
                <span className="text-[var(--muted)] w-32 shrink-0">
                  filmes chegando
                </span>
                <span className="tabular-nums">
                  {blocks(t.scores.tmdb_upcoming)}
                </span>
                <span className="text-[var(--muted)] truncate">
                  {t.evidence.tmdb_titles.length
                    ? `${t.evidence.tmdb_titles.length} casaram`
                    : "nenhum casa"}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[var(--muted)] w-32 shrink-0">
                  esquentando
                </span>
                <span className="tabular-nums">
                  {blocks(t.scores.momentum)}
                </span>
                <span className="text-[var(--muted)]">
                  {t.evidence.momentum_counts.recent} agora ·{" "}
                  {t.evidence.momentum_counts.prior} antes
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[var(--muted)] w-32 shrink-0">
                  vizinhos batendo
                </span>
                <span className="tabular-nums">
                  {blocks(t.scores.neighbor_consensus)}
                </span>
                <span className="text-[var(--muted)]">
                  {t.evidence.n_neighbors_recent === 0
                    ? "nenhum canal recente"
                    : t.evidence.n_neighbors_recent === 1
                    ? "1 canal"
                    : `${t.evidence.n_neighbors_recent} canais`}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[var(--muted)] w-32 shrink-0">
                  você não tocou
                </span>
                <span className="tabular-nums">
                  {blocks(t.scores.coverage_gap)}
                </span>
                <span className="text-[var(--muted)]">
                  {t.evidence.own_has_p90_in_theme ? "já bateu" : "novo pra você"}
                </span>
              </div>
            </div>

            {t.evidence.tmdb_titles.length > 0 && (
              <div className="mt-4 text-xs text-[var(--muted)]">
                releases que casam:{" "}
                <span className="font-mono">
                  {t.evidence.tmdb_titles.join(" · ")}
                </span>
              </div>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
