"use client";

import { useMemo, useState } from "react";
import { api, type ScoreResponse } from "@/lib/api";

type WhenChoice = "unset" | "today_18" | "today_20" | "tomorrow_18" | "custom";

function isoForChoice(choice: WhenChoice, custom: string): string | null {
  if (choice === "unset") return null;
  if (choice === "custom") return custom || null;
  const now = new Date();
  const target = new Date(now);
  if (choice === "today_18") target.setHours(18, 0, 0, 0);
  else if (choice === "today_20") target.setHours(20, 0, 0, 0);
  else if (choice === "tomorrow_18") {
    target.setDate(target.getDate() + 1);
    target.setHours(18, 0, 0, 0);
  }
  return target.toISOString();
}

export default function AvaliarPage() {
  const [title, setTitle] = useState("");
  const [duration, setDuration] = useState(40);
  const [channelId, setChannelId] = useState("");
  const [whenChoice, setWhenChoice] = useState<WhenChoice>("unset");
  const [customWhen, setCustomWhen] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const publishedAt = useMemo(
    () => isoForChoice(whenChoice, customWhen),
    [whenChoice, customWhen],
  );

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
          published_at: publishedAt,
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
          <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
            Pretende publicar quando? <span className="text-[var(--muted)]">(opcional)</span>
          </label>
          <div className="flex flex-wrap gap-2">
            {[
              { v: "unset" as const, l: "deixar de fora" },
              { v: "today_18" as const, l: "hoje 18h" },
              { v: "today_20" as const, l: "hoje 20h" },
              { v: "tomorrow_18" as const, l: "amanhã 18h" },
              { v: "custom" as const, l: "outro horário…" },
            ].map((opt) => {
              const active = whenChoice === opt.v;
              return (
                <button
                  key={opt.v}
                  type="button"
                  onClick={() => setWhenChoice(opt.v)}
                  className="text-xs uppercase tracking-wider px-3 py-1.5 border transition-colors"
                  style={{
                    fontFamily: "var(--font-display)",
                    borderColor: active ? "var(--accent)" : "var(--border)",
                    color: active ? "var(--text)" : "var(--muted)",
                    background: "transparent",
                  }}
                >
                  {opt.l}
                </button>
              );
            })}
          </div>
          {whenChoice === "custom" && (
            <input
              type="datetime-local"
              value={customWhen.slice(0, 16)}
              onChange={(e) =>
                setCustomWhen(
                  e.target.value ? new Date(e.target.value).toISOString() : "",
                )
              }
              className="mt-2 bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm font-mono focus:outline-none focus:border-[var(--accent)]"
            />
          )}
          <div className="text-xs text-[var(--muted)] mt-2 max-w-xl">
            "Deixar de fora" omite hora, dia da semana, semana do Halloween e
            distância de lançamento da explicação. Quando você escolhe um
            horário, eles voltam à conta.
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
          </div>

          <div className="card md:col-span-2">
            <h2 className="text-base mb-1">Por que esse score?</h2>
            <p className="text-xs text-[var(--muted)] mb-1">
              Duas referências independentes, leia separado:
            </p>
            <ul className="text-xs text-[var(--muted)] mb-3 list-disc list-inside space-y-0.5">
              <li>
                <span style={{ color: "#5BC076" }}>▲ ajudou</span> /{" "}
                <span style={{ color: "var(--accent)" }}>▼ atrapalhou</span>:
                o que o modelo previu pra <strong>esse título nesse canal</strong>
              </li>
              <li>
                <span className="font-mono">Outliers do seu tamanho:</span> o
                que vídeos vencedores de canais da mesma faixa (1k–10k subs)
                costumam ter — pode discordar do modelo, e isso é informação
                em si.
              </li>
            </ul>
            <div className="text-xs mb-3 p-2 border border-[var(--border)]" style={{ background: "var(--surface-2)", color: "#A8A39A" }}>
              <strong style={{ color: "#D4AF37" }}>⚠ ainda em calibração:</strong>{" "}
              o modelo está aprendendo. Hoje ele tem ~151 vídeos vencedores
              da sua faixa de canal (1k–10k inscritos) como referência;
              dimensões com efeito muito pequeno são omitidas pra não
              poluir. Vai ficar mais preciso quando acumular semanas de
              histórico das views.
              {result.n_neutral_features > 0 && (
                <>
                  {" "}
                  <span className="font-mono">
                    ({result.n_neutral_features} dimensões sem efeito
                    relevante foram omitidas.)
                  </span>
                </>
              )}
            </div>
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
