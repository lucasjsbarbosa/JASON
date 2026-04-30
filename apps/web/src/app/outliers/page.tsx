"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api,
  type Channel,
  type OutlierVideo,
} from "@/lib/api";

export default function OutliersPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState<string>("");
  const [minPercentile, setMinPercentile] = useState<number>(0);
  const [items, setItems] = useState<OutlierVideo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Channel[]>("/api/channels")
      .then(setChannels)
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    params.set("limit", "40");
    if (channelId) params.set("channel_id", channelId);
    if (minPercentile > 0) params.set("min_percentile", String(minPercentile));
    api<OutlierVideo[]>(`/api/outliers?${params}`)
      .then(setItems)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [channelId, minPercentile]);

  const groupedChannels = useMemo(() => {
    const tiers = [
      { label: "Muito grande (1M+)", min: 1_000_000 },
      { label: "Grande (100k–1M)", min: 100_000 },
      { label: "Médio (10k–100k)", min: 10_000 },
      { label: "Pequeno (até 10k)", min: 0 },
    ];
    return tiers.map((t, i) => {
      const upper = i === 0 ? Infinity : tiers[i - 1].min;
      const list = channels
        .filter((c) => (c.subs ?? 0) >= t.min && (c.subs ?? 0) < upper)
        .sort((a, b) => (b.subs ?? 0) - (a.subs ?? 0));
      return { ...t, list };
    });
  }, [channels]);

  return (
    <div className="space-y-8 max-w-6xl">
      <section>
        <h1 className="text-2xl">Outliers do nicho</h1>
        <p className="text-sm text-[var(--muted)] mt-2 max-w-3xl">
          Vídeos que mais bombaram em cada canal acompanhado, ordenados pelo
          quanto superaram a média do próprio canal. Use como inspiração de
          packaging vencedor — mas lembrando: comparar canal de 3k com canal
          de 3M tem armadilha (use o filtro por canal pra comparações justas).
        </p>
      </section>

      <section className="card flex flex-wrap gap-4 items-end">
        <div className="flex-1 min-w-[20rem]">
          <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
            Canal
          </label>
          <select
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="">Todos os canais ({channels.length})</option>
            {groupedChannels.map((g) =>
              g.list.length > 0 ? (
                <optgroup key={g.label} label={g.label}>
                  {g.list.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                      {c.subs ? ` — ${formatSubs(c.subs)} subs` : ""}
                    </option>
                  ))}
                </optgroup>
              ) : null,
            )}
          </select>
        </div>
        <div>
          <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
            Percentil mínimo
          </label>
          <select
            value={minPercentile}
            onChange={(e) => setMinPercentile(Number(e.target.value))}
            className="bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm focus:outline-none focus:border-[var(--accent)]"
          >
            <option value={0}>Todos</option>
            <option value={75}>Acima da média (≥75)</option>
            <option value={90}>Outliers (≥90)</option>
            <option value={95}>Top 5% (≥95)</option>
            <option value={99}>Topo absoluto (≥99)</option>
          </select>
        </div>
      </section>

      {error && (
        <div className="border border-[var(--accent)] text-[var(--accent)] p-3 text-sm font-mono">
          {error}
        </div>
      )}

      {loading && (
        <div className="text-sm text-[var(--muted)] font-mono">Carregando…</div>
      )}

      <section className="space-y-3">
        {items.map((v, i) => (
          <article key={v.id} className="card flex gap-4 items-start">
            <div className="w-40 shrink-0">
              {v.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={v.thumbnail_url} alt={v.title} className="w-full" />
              ) : (
                <div
                  className="w-full aspect-video flex items-center justify-center text-3xl text-[var(--muted)]"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  #{(i + 1).toString().padStart(2, "0")}
                </div>
              )}
            </div>
            <div className="flex-1">
              <div className="text-xs text-[var(--muted)] uppercase tracking-wider mb-1">
                {v.channel}
              </div>
              <h3 className="text-sm font-semibold normal-case">{v.title}</h3>
              <div className="mt-2 flex flex-wrap gap-2">
                {v.multiplier_human && (
                  <span
                    className={`pill ${
                      v.multiplier && v.multiplier >= 3
                        ? "pill-hot"
                        : v.multiplier && v.multiplier >= 1.5
                        ? "pill-mid"
                        : ""
                    }`}
                  >
                    {v.multiplier_human}
                  </span>
                )}
                {v.percentile_human && (
                  <span
                    className={`pill ${
                      v.percentile && v.percentile >= 95
                        ? "pill-hot"
                        : "pill-mid"
                    }`}
                  >
                    {v.percentile_human}
                  </span>
                )}
                {v.views !== null && (
                  <span className="pill">
                    {v.views.toLocaleString("pt-BR")} views
                  </span>
                )}
                {v.theme_label && (
                  <span className="pill">subgênero: {v.theme_label}</span>
                )}
                {v.franchise_label && (
                  <span className="pill">franquia: {v.franchise_label}</span>
                )}
              </div>
              <div className="mt-2 text-xs text-[var(--muted)] font-mono">
                <a href={`https://youtu.be/${v.id}`} target="_blank" rel="noreferrer">
                  abrir no YouTube ↗
                </a>
              </div>
            </div>
          </article>
        ))}
        {!loading && items.length === 0 && (
          <div className="text-sm text-[var(--muted)]">
            Nenhum vídeo encontrado com os filtros selecionados.
          </div>
        )}
      </section>
    </div>
  );
}

function formatSubs(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
}
