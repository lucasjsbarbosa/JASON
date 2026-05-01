import { BootstrapRibbon } from "./_components/bootstrap-ribbon";
import {
  api,
  type OutlierVideo,
  type OwnMetrics,
  type PackagingGapRow,
  type ThemeCoverage,
} from "@/lib/api";

async function getData() {
  try {
    const [metrics, top, gap, themes] = await Promise.all([
      api<OwnMetrics>("/api/own/metrics"),
      api<OutlierVideo[]>("/api/own/top-videos?limit=8"),
      api<PackagingGapRow[]>("/api/own/packaging-gap"),
      api<ThemeCoverage[]>("/api/own/themes"),
    ]);
    return { metrics, top, gap, themes, error: null as string | null };
  } catch (e) {
    return {
      metrics: null,
      top: [],
      gap: [],
      themes: [],
      error: (e as Error).message,
    };
  }
}

function pctBlocks(v: number) {
  // 0..100 → 5 bloquinhos. Não diferencia 8% de 12%, mas dá leitura rápida.
  const filled = Math.round(Math.max(0, Math.min(100, v)) / 20);
  return "▮".repeat(filled) + "▯".repeat(5 - filled);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "·";
  return new Date(iso).toLocaleDateString("pt-BR");
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <div className="text-[0.7rem] tracking-widest text-[var(--muted)] uppercase">{label}</div>
      <div className="font-mono text-3xl mt-1">{value}</div>
      {hint && <div className="text-xs text-[var(--muted)] mt-1">{hint}</div>}
    </div>
  );
}

export default async function Home() {
  const { metrics, top, gap, themes, error } = await getData();

  // Sort packaging-gap by absolute distance — biggest mismatches first.
  const sortedGap = [...gap].sort(
    (a, b) => Math.abs(b.diff_pp) - Math.abs(a.diff_pp),
  );

  // Filter themes the user has actually published in (own_n > 0), and
  // surface biggest underperformers + biggest overperformers vs niche.
  const themesWithOwn = themes.filter((t) => t.own_n > 0);
  const themesByGap = [...themesWithOwn]
    .filter(
      (t) =>
        t.own_avg_mult !== null &&
        t.niche_avg_mult !== null &&
        t.niche_avg_mult > 0 &&
        (t.niche_n ?? 0) >= 3,
    )
    .map((t) => ({
      ...t,
      ratio: (t.own_avg_mult ?? 0) / (t.niche_avg_mult ?? 1),
    }))
    .sort((a, b) => Math.abs(Math.log(b.ratio)) - Math.abs(Math.log(a.ratio)))
    .slice(0, 8);

  if (error) {
    return (
      <div>
        <h1 className="text-2xl">backend offline</h1>
        <p className="text-sm text-[var(--muted)] mt-2 font-mono">{error}</p>
        <p className="mt-4">
          Suba a API: <code className="bg-[var(--surface)] px-2 py-1">jason api</code>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-2xl">Painel @babygiulybaby</h1>
        <p className="text-sm text-[var(--muted)] mt-2 max-w-2xl">
          Visão rápida do canal próprio. Para análise comparativa, gap de packaging,
          subgêneros cobertos e geração de títulos, navegue pelas abas acima.
        </p>
      </section>

      <BootstrapRibbon>
        <strong style={{ color: "var(--text)" }}>Ainda em calibração:</strong>{" "}
        os multipliers usam o snapshot de views mais recente, não a janela
        estabilizada de 28 dias. Vai ficar mais preciso conforme as semanas
        passarem e o histórico amadurecer.
      </BootstrapRibbon>

      <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Vídeos longos"
          value={metrics ? metrics.long_videos.toLocaleString("pt-BR") : "·"}
        />
        <MetricCard
          label="Último upload"
          value={metrics ? fmtDate(metrics.last_upload) : "·"}
        />
        <MetricCard
          label="Maior outlier"
          value={metrics?.top_multiplier ? `${metrics.top_multiplier.toFixed(1)}x` : "·"}
          hint={metrics?.top_multiplier_human ?? undefined}
        />
        <MetricCard
          label="Vídeos acima da média"
          value={metrics ? metrics.soft_outliers.toLocaleString("pt-BR") : "·"}
          hint="≥ 1.5x da mediana do canal"
        />
      </section>

      {sortedGap.length > 0 && (
        <section>
          <h2 className="text-lg mb-2">Packaging — você vs vencedores do seu tamanho</h2>
          <p className="text-sm text-[var(--muted)] mb-4 max-w-3xl">
            Compara seus padrões de título com vídeos top-10% de canais 1k–10k
            inscritos (a sua faixa). Não é cobrança pra copiar, é dimensão do
            que distingue os dois estilos.
          </p>
          <div className="card">
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
                    seu tamanho
                  </th>
                  <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                    diferença
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedGap.map((g) => {
                  const diff = Math.round(g.diff_pp);
                  const small = Math.abs(g.diff_pp) < 5;
                  return (
                    <tr
                      key={g.feature}
                      className="border-b border-[var(--border)]/50"
                    >
                      <td className="py-2">{g.feature}</td>
                      <td className="text-right tabular-nums font-mono text-xs">
                        <span className="opacity-60 mr-2">
                          {pctBlocks(g.own_pct)}
                        </span>
                        {g.own_pct.toFixed(0)}%
                      </td>
                      <td className="text-right tabular-nums font-mono text-xs text-[var(--muted)]">
                        <span className="opacity-60 mr-2">
                          {pctBlocks(g.niche_pct)}
                        </span>
                        {g.niche_pct.toFixed(0)}%
                      </td>
                      <td
                        className="text-right tabular-nums font-mono text-xs"
                        style={{
                          color: small ? "var(--muted)" : "var(--text)",
                        }}
                      >
                        {small
                          ? "≈ igual"
                          : diff > 0
                          ? `você usa +${diff} a cada 100`
                          : `você usa ${diff} a cada 100`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {themesByGap.length > 0 && (
        <section>
          <h2 className="text-lg mb-2">Subgêneros — sua média vs canais do seu tamanho</h2>
          <p className="text-sm text-[var(--muted)] mb-4 max-w-3xl">
            Quanto cada subgênero rendeu pra você (média do multiplier dos
            seus vídeos do tema) comparado com vizinhos da mesma faixa de
            inscritos. ▼ você fica abaixo · ▲ você fica acima.
          </p>
          <div className="card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)]">
                  <th className="text-left py-2 font-mono text-xs text-[var(--muted)]">
                    subgênero
                  </th>
                  <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                    seus vídeos
                  </th>
                  <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                    sua média
                  </th>
                  <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                    seu tamanho
                  </th>
                  <th className="text-right py-2 font-mono text-xs text-[var(--muted)]">
                    razão
                  </th>
                </tr>
              </thead>
              <tbody>
                {themesByGap.map((t) => {
                  const arrow = t.ratio >= 1.2 ? "▲" : t.ratio <= 0.8 ? "▼" : "≈";
                  const color =
                    t.ratio >= 1.2
                      ? "#5BC076"
                      : t.ratio <= 0.8
                      ? "var(--accent)"
                      : "var(--muted)";
                  return (
                    <tr
                      key={t.theme}
                      className="border-b border-[var(--border)]/50"
                    >
                      <td className="py-2">{t.theme}</td>
                      <td className="text-right tabular-nums font-mono text-xs text-[var(--muted)]">
                        {t.own_n}
                      </td>
                      <td className="text-right tabular-nums font-mono text-xs">
                        {(t.own_avg_mult ?? 0).toFixed(1)}x
                      </td>
                      <td className="text-right tabular-nums font-mono text-xs text-[var(--muted)]">
                        {(t.niche_avg_mult ?? 0).toFixed(1)}x
                      </td>
                      <td
                        className="text-right tabular-nums font-mono text-xs"
                        style={{ color }}
                      >
                        {arrow} {t.ratio.toFixed(1)}×
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="text-xs text-[var(--muted)] mt-3 max-w-2xl">
              "Sua média" = mediana de multiplier dos seus vídeos com esse
              subgênero. "Seu tamanho" = o mesmo, calculado em vizinhos
              1k–10k. Razão = sua/deles.
            </p>
          </div>
        </section>
      )}

      <section>
        <h2 className="text-lg mb-4">Vídeos que mais bombaram (relativos ao próprio canal)</h2>
        <p className="text-sm text-[var(--muted)] mb-4 max-w-3xl">
          Ordenado por <span className="font-mono">views ÷ mediana do canal</span> naquele
          período. Por isso um vídeo de 2k pode ficar acima de um de 20k: se os vizinhos
          da época tinham mais views, o de 20k foi só normal pro canal.
        </p>
        <div className="space-y-3">
          {top.map((v, i) => (
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
                <h3
                  className="text-sm font-semibold normal-case tracking-normal"
                  style={{ fontFamily: "var(--font-sans)" }}
                >
                  #{(i + 1).toString().padStart(2, "0")} · {v.title}
                </h3>
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
                      className={`pill ${v.percentile && v.percentile >= 95 ? "pill-hot" : "pill-mid"}`}
                    >
                      {v.percentile_human}
                    </span>
                  )}
                  {v.views !== null && (
                    <span className="pill">{v.views.toLocaleString("pt-BR")} views</span>
                  )}
                  {v.theme_label && <span className="pill">subgênero: {v.theme_label}</span>}
                </div>
                <div className="mt-2 text-xs text-[var(--muted)] font-mono">
                  <a
                    href={`https://youtu.be/${v.id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    abrir no YouTube ↗
                  </a>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
