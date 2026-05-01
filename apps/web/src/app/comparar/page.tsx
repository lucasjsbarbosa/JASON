"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type Channel, type CompareResponse } from "@/lib/api";

const PACKAGING_LABELS: Record<string, string> = {
  has_explained_keyword: "EXPLICADO / ENTENDA",
  has_ranking_keyword: "TOP / MELHORES / PIORES",
  has_curiosity_keyword: "POR QUE / NÃO SABIAM",
  has_extreme_adjective: "PERTURBADOR / INSANO",
  has_caps_word: "Palavra em CAPS",
  has_number: "Número (Top 10, 7…)",
  has_question_mark: "Pergunta?",
  has_first_person: "1ª pessoa (eu, meu)",
};

function pct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

export default function CompararPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [neighborId, setNeighborId] = useState<string>("");
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Channel[]>("/api/channels")
      .then((r) => {
        setChannels(r);
        // Default neighbor: similar tier (1k-50k) — comparing 3.5k subs vs
        // 3M+ subs is the trap the /outliers page warns about. Pick the
        // closest-sized channel instead of just the first one.
        const own = r.find((c) => c.handle === "babygiulybaby");
        const ownSubs = own?.subs ?? 3500;
        const candidates = r
          .filter((c) => c.handle !== "babygiulybaby" && (c.subs ?? 0) > 0)
          .sort(
            (a, b) =>
              Math.abs((a.subs ?? 0) - ownSubs) -
              Math.abs((b.subs ?? 0) - ownSubs),
          );
        if (candidates[0]) setNeighborId(candidates[0].id);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (!neighborId) return;
    setLoading(true);
    setError(null);
    api<CompareResponse>(`/api/compare?neighbor_id=${neighborId}`)
      .then(setData)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [neighborId]);

  const sortedChannels = useMemo(
    () => [...channels].sort((a, b) => (b.subs ?? 0) - (a.subs ?? 0)),
    [channels],
  );

  return (
    <div className="space-y-8 max-w-5xl">
      <section>
        <h1 className="text-2xl">Comparar canais</h1>
        <p className="text-sm text-[var(--muted)] mt-2 max-w-3xl">
          Você (@babygiulybaby) vs um vizinho do nicho, lado a lado.
          Mostra: o que ele faz no título que você não faz, e em quais
          subgêneros ele bate forte que você ainda não tocou.
        </p>
      </section>

      <section className="card">
        <label className="block text-xs uppercase tracking-wider mb-2 text-[var(--muted)]">
          Vizinho
        </label>
        <select
          value={neighborId}
          onChange={(e) => setNeighborId(e.target.value)}
          className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm focus:outline-none focus:border-[var(--accent)]"
        >
          {sortedChannels.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title} {c.subs ? `· ${c.subs.toLocaleString("pt-BR")} insc` : ""}
            </option>
          ))}
        </select>
      </section>

      {error && (
        <div className="card border-[var(--accent)] text-[var(--accent)] text-sm">
          {error}
        </div>
      )}

      {loading && <div className="text-sm text-[var(--muted)]">Carregando…</div>}

      {data && (
        <>
          <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="card">
              <div className="text-xs uppercase tracking-wider text-[var(--muted)]">
                você
              </div>
              <div className="text-lg mt-1">{data.own.title}</div>
              <div className="text-xs text-[var(--muted)] mt-1">
                {data.own.subs.toLocaleString("pt-BR")} inscritos · {data.own.long_total} long-form
              </div>
              <div className="mt-3 text-sm space-y-1">
                <div>
                  % de vídeos que viraram outlier:{" "}
                  <span className="font-mono">{pct(data.own.outlier_rate)}</span>
                </div>
                <div>
                  Views típicas aos 28 dias:{" "}
                  <span className="font-mono">
                    {data.own.median_views_at_28d?.toLocaleString("pt-BR") ??
                      "—"}
                  </span>
                </div>
              </div>
            </div>
            <div className="card">
              <div className="text-xs uppercase tracking-wider text-[var(--muted)]">
                vizinho
              </div>
              <div className="text-lg mt-1">{data.neighbor.title}</div>
              <div className="text-xs text-[var(--muted)] mt-1">
                {data.neighbor.subs.toLocaleString("pt-BR")} inscritos ·{" "}
                {data.neighbor.long_total} long-form
              </div>
              <div className="mt-3 text-sm space-y-1">
                <div>
                  % de vídeos que viraram outlier:{" "}
                  <span className="font-mono">
                    {pct(data.neighbor.outlier_rate)}
                  </span>
                </div>
                <div>
                  Views típicas aos 28 dias:{" "}
                  <span className="font-mono">
                    {data.neighbor.median_views_at_28d?.toLocaleString(
                      "pt-BR",
                    ) ?? "—"}
                  </span>
                </div>
              </div>
            </div>
          </section>

          <section className="card">
            <h2 className="text-sm uppercase tracking-wider text-[var(--muted)] mb-4">
              Diferença de packaging
            </h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="text-left py-2 font-mono text-xs text-[var(--muted)]">
                    padrão
                  </th>
                  <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                    você
                  </th>
                  <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                    vizinho
                  </th>
                  <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                    diferença
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.packaging_diff.map((d) => {
                  const deltaPct = Math.round(d.delta * 100);
                  const small = Math.abs(d.delta) < 0.05;
                  const color = small ? "var(--muted)" : "var(--text)";
                  return (
                    <tr
                      key={d.feature}
                      className="border-b border-[var(--border)]/50"
                    >
                      <td className="py-2">
                        {PACKAGING_LABELS[d.feature] ?? d.feature}
                      </td>
                      <td className="text-right tabular-nums">
                        {pct(d.own_pct)}
                      </td>
                      <td className="text-right tabular-nums">
                        {pct(d.neighbor_pct)}
                      </td>
                      <td
                        className="text-right tabular-nums font-mono"
                        style={{ color }}
                      >
                        {small
                          ? "≈ igual"
                          : deltaPct > 0
                          ? `+${deltaPct} a cada 100`
                          : `${deltaPct} a cada 100`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="text-xs text-[var(--muted)] mt-4 max-w-2xl">
              "+12 a cada 100" = pra cada 100 vídeos, vizinho usa esse padrão
              em 12 a mais que você. É descrição de estilo, não cobrança
              pra copiar.
            </p>
          </section>

          {data.coverage_gap.length > 0 && (
            <section className="card">
              <h2 className="text-sm uppercase tracking-wider text-[var(--muted)] mb-4">
                Subgêneros que o vizinho costuma viralizar e você ainda não tocou
              </h2>
              <ul className="space-y-2 text-sm">
                {data.coverage_gap.map((t) => (
                  <li
                    key={t.theme_id}
                    className="flex justify-between border-b border-[var(--border)]/50 py-2"
                  >
                    <span>{t.label_human ?? t.label ?? `tema ${t.theme_id}`}</span>
                    <span className="font-mono text-[var(--muted)]">
                      {t.outlier_count} vídeos que viralizaram no vizinho
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
