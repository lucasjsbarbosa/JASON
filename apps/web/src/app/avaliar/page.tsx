"use client";

import { useState } from "react";
import { api, type ScoreResponse } from "@/lib/api";

export default function AvaliarPage() {
  const [title, setTitle] = useState(
    "FINAL EXPLICADO de Hereditário (2018)",
  );
  const [duration, setDuration] = useState(40);
  const [channelId, setChannelId] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!title.trim()) {
      setError("Cola um título primeiro.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await api<ScoreResponse>("/api/score", {
        method: "POST",
        body: JSON.stringify({
          title,
          duration_min: duration,
          channel_id: channelId.trim() || null,
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
        <h1 className="text-2xl">Avaliar um título</h1>
        <p className="text-sm text-[var(--muted)] mt-2 max-w-2xl">
          Cola um título candidato. JASON prevê quanto ele performaria em
          comparação com a média do canal e mostra o que ajudou ou atrapalhou
          a previsão, em ordem de importância.
        </p>
      </section>

      <section className="card space-y-4">
        <div>
          <label className="block text-sm uppercase tracking-wider mb-2 text-[var(--muted)]">
            Título do vídeo
          </label>
          <textarea
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-3 font-sans text-sm min-h-[3rem] focus:outline-none focus:border-[var(--accent)]"
            rows={2}
          />
          <div className="text-xs text-[var(--muted)] mt-1 font-mono">
            {title.length} caracteres
          </div>
        </div>

        <div>
          <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
            Duração estimada (minutos)
          </label>
          <input
            type="number"
            value={duration}
            min={1}
            max={180}
            step={1}
            onChange={(e) => setDuration(Number(e.target.value))}
            className="w-40 bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm font-mono focus:outline-none focus:border-[var(--accent)]"
          />
          <span className="text-xs text-[var(--muted)] ml-3 font-mono">
            = {duration * 60}s
          </span>
          <div className="text-xs text-[var(--muted)] mt-1">
            Análises longas (30–50 min) costumam performar melhor no nicho.
          </div>
        </div>

        <div>
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs uppercase tracking-wider text-[var(--muted)] hover:text-[var(--text)]"
          >
            {showAdvanced ? "▾" : "▸"} opções avançadas
          </button>
          {showAdvanced && (
            <div className="mt-3">
              <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
                ID do canal (UC…)
              </label>
              <input
                type="text"
                value={channelId}
                onChange={(e) => setChannelId(e.target.value)}
                placeholder="default: canal próprio"
                className="w-full max-w-md bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm font-mono focus:outline-none focus:border-[var(--accent)]"
              />
              <div className="text-xs text-[var(--muted)] mt-1">
                Vazio = canal próprio (@babygiulybaby).
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={submit}
            disabled={loading}
            className="px-6 py-2 border border-[var(--accent)] text-[var(--text)] hover:bg-[var(--accent)] hover:text-[var(--bg)] uppercase tracking-wider text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {loading ? "Avaliando..." : "Avaliar"}
          </button>
        </div>

        {error && (
          <div className="border border-[var(--accent)] text-[var(--accent)] p-3 text-sm font-mono">
            {error}
          </div>
        )}
      </section>

      {result && (
        <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="card md:col-span-1 flex flex-col items-start">
            <div className="text-[0.7rem] tracking-widest text-[var(--muted)] uppercase">
              Comparado à média do canal
            </div>
            <div className="font-mono text-5xl mt-2 leading-none">
              {result.multiplier.toFixed(2)}
              <span className="text-3xl">x</span>
            </div>
            <div className="text-sm text-[var(--text)] mt-3">
              {result.multiplier_human}
            </div>
            <div className="text-xs text-[var(--muted)] mt-4 font-mono">
              log_multiplier = {result.log_multiplier.toFixed(4)}
            </div>
          </div>

          <div className="card md:col-span-2">
            <h2 className="text-base mb-1">Por que esse score?</h2>
            <p className="text-xs text-[var(--muted)] mb-1">
              Duas referências independentes — leia separado:
            </p>
            <ul className="text-xs text-[var(--muted)] mb-4 list-disc list-inside space-y-0.5">
              <li>
                <span style={{ color: "#5BC076" }}>▲ ajudou</span> /{" "}
                <span style={{ color: "var(--accent)" }}>▼ atrapalhou</span> —
                o modelo previu pro <strong>seu canal</strong> (3.5k subs,
                padrões da @babygiulybaby)
              </li>
              <li>
                <span className="font-mono">Nicho geral:</span> estatística
                dos vídeos top-10% nos 25 canais ingeridos
              </li>
            </ul>
            <p className="text-xs mb-4" style={{ color: "#A8A39A" }}>
              Quando os dois divergem (ex: modelo diz &quot;ajudou&quot; mas
              nicho diz &quot;abaixo da faixa vencedora&quot;), é sinal real
              de que seu canal performa diferente do nicho médio.
            </p>
            <div className="space-y-2">
              {result.contributions.map((c, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 py-2 border-b border-[var(--border)] last:border-b-0"
                >
                  <span
                    style={{ color: c.color, width: "1rem" }}
                    className="text-center text-base mt-0.5"
                  >
                    {c.direction === "up" ? "▲" : "▼"}
                  </span>
                  <div className="flex-1">
                    <div className="text-sm">{c.label}</div>
                    <div className="text-xs text-[var(--muted)] font-mono mt-0.5">
                      {c.value} · {c.verb}{" "}
                      <span style={{ color: c.color }}>
                        ({c.contribution >= 0 ? "+" : ""}
                        {c.contribution.toFixed(2)})
                      </span>
                    </div>
                    {c.context && (
                      <div className="text-xs mt-1" style={{ color: "#A8A39A" }}>
                        {c.context}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
