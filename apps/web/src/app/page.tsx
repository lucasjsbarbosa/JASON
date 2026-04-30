import { api, type OutlierVideo, type OwnMetrics } from "@/lib/api";

async function getData() {
  try {
    const [metrics, top] = await Promise.all([
      api<OwnMetrics>("/api/own/metrics"),
      api<OutlierVideo[]>("/api/own/top-videos?limit=8"),
    ]);
    return { metrics, top, error: null as string | null };
  } catch (e) {
    return { metrics: null, top: [], error: (e as Error).message };
  }
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
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
  const { metrics, top, error } = await getData();

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

      <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Vídeos longos"
          value={metrics ? metrics.long_videos.toLocaleString("pt-BR") : "—"}
        />
        <MetricCard
          label="Último upload"
          value={metrics ? fmtDate(metrics.last_upload) : "—"}
        />
        <MetricCard
          label="Maior outlier"
          value={metrics?.top_multiplier ? `${metrics.top_multiplier.toFixed(1)}x` : "—"}
          hint={metrics?.top_multiplier_human ?? undefined}
        />
        <MetricCard
          label="Vídeos acima da média"
          value={metrics ? metrics.soft_outliers.toLocaleString("pt-BR") : "—"}
          hint="≥ 1.5x da mediana do canal"
        />
      </section>

      <section>
        <h2 className="text-lg mb-4">Vídeos que mais bombaram (relativos ao próprio canal)</h2>
        <p className="text-sm text-[var(--muted)] mb-4 max-w-3xl">
          Ordenado por <span className="font-mono">views ÷ mediana do canal</span> naquele
          período. Por isso um vídeo de 2k pode ficar acima de um de 20k — se os vizinhos
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
