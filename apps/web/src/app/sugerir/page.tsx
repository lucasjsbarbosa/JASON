"use client";

import { useState } from "react";
import { api, type SuggestResponse } from "@/lib/api";

export default function SugerirPage() {
  const [transcript, setTranscript] = useState("");
  const [theme, setTheme] = useState("");
  const [num, setNum] = useState(10);
  const [duration, setDuration] = useState(40);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SuggestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  async function submit() {
    if (!transcript.trim()) {
      setError("Cola um resumo ou transcrição primeiro.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setOpenIdx(null);
    try {
      const r = await api<SuggestResponse>("/api/suggest", {
        method: "POST",
        body: JSON.stringify({
          transcript,
          theme: theme || null,
          num_candidates: num,
          duration_min: duration,
        }),
      });
      setResult(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8 max-w-4xl">
      <section>
        <h1 className="text-2xl">Sugerir título</h1>
        <p className="text-sm text-[var(--muted)] mt-2 max-w-2xl">
          Cola um resumo ou transcrição do vídeo. JASON busca os títulos do
          nicho que mais bombaram em vídeos parecidos, manda pra Claude gerar
          {" "}{num}{" "}candidatos no estilo do nicho, e ranqueia pelo modelo do
          canal próprio. Cada candidato vem com{" "}
          <span style={{ color: "var(--accent)" }}>por quê</span> ele recebeu
          aquele score.
        </p>
      </section>

      <section className="card space-y-4">
        <div>
          <label className="block text-sm uppercase tracking-wider mb-2 text-[var(--muted)]">
            Resumo / transcrição
          </label>
          <textarea
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder="O vídeo apresenta uma análise completa de V/H/S/Halloween..."
            className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-3 font-sans text-sm min-h-40 focus:outline-none focus:border-[var(--accent)]"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
              Tema/franquia (opcional)
            </label>
            <input
              type="text"
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              placeholder="ex: V/H/S, possessão, slasher"
              className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div>
            <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
              Quantos candidatos
            </label>
            <input
              type="number"
              value={num}
              min={3}
              max={20}
              onChange={(e) => setNum(Number(e.target.value))}
              className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm font-mono focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div>
            <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
              Duração estimada (min)
            </label>
            <input
              type="number"
              value={duration}
              min={1}
              max={180}
              step={1}
              onChange={(e) => setDuration(Number(e.target.value))}
              className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm font-mono focus:outline-none focus:border-[var(--accent)]"
            />
            <div className="text-xs text-[var(--muted)] mt-1 font-mono">
              = {duration * 60}s
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={submit}
            disabled={loading}
            className="px-6 py-2 border border-[var(--accent)] text-[var(--text)] hover:bg-[var(--accent)] hover:text-[var(--bg)] uppercase tracking-wider text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {loading ? "Gerando..." : "Gerar"}
          </button>
          {loading && (
            <span className="text-xs text-[var(--muted)] font-mono">
              Chamando Claude · busca RAG · ranqueando…
            </span>
          )}
        </div>

        {error && (
          <div className="border border-[var(--accent)] text-[var(--accent)] p-3 text-sm font-mono">
            {error}
          </div>
        )}
      </section>

      {result && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg">Candidatos</h2>
            <div className="text-xs text-[var(--muted)] font-mono">
              RAG buscou {result.rag_outlier_count} outliers do nicho
              {!result.model_trained &&
                " · modelo não treinado (sem score)"}
            </div>
          </div>
          <p className="text-sm text-[var(--muted)] mb-4">
            Ordenado pelo previsto.{" "}
            <span style={{ color: "#5BC076" }}>▲ verde</span> = padrão ajudou
            ·{" "}
            <span style={{ color: "var(--accent)" }}>▼ vermelho</span> =
            atrapalhou. Clique pra abrir o{" "}
            <em>por quê</em>.
          </p>

          <div className="space-y-2">
            {result.candidates.map((c, i) => {
              const open = openIdx === i;
              const pillKind =
                c.multiplier && c.multiplier >= 3
                  ? "pill-hot"
                  : c.multiplier && c.multiplier >= 1.5
                  ? "pill-mid"
                  : "";
              return (
                <article
                  key={i}
                  className="card cursor-pointer"
                  onClick={() => setOpenIdx(open ? null : i)}
                >
                  <div className="flex items-center gap-4">
                    <div className="font-mono text-sm text-[var(--muted)] w-8 shrink-0">
                      {String(i + 1).padStart(2, "0")}
                    </div>
                    <span className={`pill ${pillKind} shrink-0`}>
                      {c.multiplier_human ?? "sem score"}
                    </span>
                    <div className="flex-1 text-sm">{c.title}</div>
                    <div
                      className="text-[var(--muted)] font-mono text-xs"
                      style={{ minWidth: "5rem", textAlign: "right" }}
                    >
                      {open ? "fechar ◢" : "por quê? ▾"}
                    </div>
                  </div>
                  {open && c.contributions.length > 0 && (
                    <div className="mt-3 ml-12 space-y-2 border-l border-[var(--border)] pl-4">
                      {c.contributions.map((cc, j) => (
                        <div key={j} className="flex items-start gap-3 text-sm">
                          <span
                            style={{ color: cc.color, width: "1rem" }}
                            className="text-center mt-0.5"
                          >
                            {cc.direction === "up" ? "▲" : "▼"}
                          </span>
                          <div className="flex-1">
                            <div>
                              {cc.label}{" "}
                              <span className="text-[var(--muted)] text-xs">
                                ({cc.value} · {cc.verb})
                              </span>
                            </div>
                            {cc.context && (
                              <div
                                className="text-xs mt-0.5"
                                style={{ color: "#A8A39A" }}
                              >
                                {cc.context}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  {open && c.contributions.length === 0 && (
                    <div className="mt-3 ml-12 text-xs text-[var(--muted)] font-mono">
                      Sem score (modelo ainda não treinado).
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
