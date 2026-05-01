"use client";

import { useEffect, useState } from "react";
import { api, type ChoseResponse, type SuggestResponse } from "@/lib/api";

const STORAGE_KEY = "jason.sugerir.session.v1";

type Stored = {
  transcript: string;
  theme: string;
  num: number;
  duration: number;
  result: SuggestResponse | null;
  chosenId: number | null;
  savedAt: number;
};

export default function SugerirPage() {
  const [transcript, setTranscript] = useState("");
  const [theme, setTheme] = useState("");
  const [num, setNum] = useState(10);
  const [duration, setDuration] = useState(40);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SuggestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [chosenId, setChosenId] = useState<number | null>(null);
  const [choosing, setChoosing] = useState<number | null>(null);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from localStorage on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const s: Stored = JSON.parse(raw);
        setTranscript(s.transcript ?? "");
        setTheme(s.theme ?? "");
        setNum(s.num ?? 10);
        setDuration(s.duration ?? 40);
        setResult(s.result ?? null);
        setChosenId(s.chosenId ?? null);
      }
    } catch {}
    setHydrated(true);
  }, []);

  // Persist whenever inputs/result/chosen change (only after hydration).
  useEffect(() => {
    if (!hydrated) return;
    const s: Stored = {
      transcript,
      theme,
      num,
      duration,
      result,
      chosenId,
      savedAt: Date.now(),
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch {}
  }, [hydrated, transcript, theme, num, duration, result, chosenId]);

  async function toggleChose(suggestionId: number) {
    setChoosing(suggestionId);
    setError(null);
    const wasChosen = chosenId === suggestionId;
    try {
      if (wasChosen) {
        await api(`/api/suggestions/${suggestionId}/chose`, {
          method: "DELETE",
        });
        setChosenId(null);
      } else {
        const r = await api<ChoseResponse>(
          `/api/suggestions/${suggestionId}/chose`,
          { method: "POST" },
        );
        setChosenId(r.suggestion_id);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChoosing(null);
    }
  }

  function clearSession() {
    setTranscript("");
    setTheme("");
    setResult(null);
    setChosenId(null);
    setOpenIdx(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {}
  }

  async function submit() {
    if (!transcript.trim()) {
      setError("Cola um resumo ou transcrição primeiro.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setChosenId(null);
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
        <div className="text-xs uppercase tracking-wider text-[var(--muted)]">
          o que esta tela faz
        </div>
        <h1 className="text-2xl mt-1">Sugerir título do vídeo</h1>
        <p className="text-sm text-[var(--muted)] mt-3 max-w-2xl">
          Você cola um resumo (ou transcrição) do vídeo aqui. JASON puxa os
          títulos do nicho que mais bombaram em vídeos parecidos, pede pra Claude
          gerar {num} variações no estilo do canal, e ranqueia pelo modelo do
          seu canal. <strong>Esta tela só sugere o título</strong> — pra escolher
          a thumbnail use <a href="/thumbs" className="text-[var(--accent)]">Sugerir
          thumb</a>; pra escolher o tema do próximo vídeo use{" "}
          <a href="/temas" className="text-[var(--accent)]">Sugerir tema</a>.
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
              Buscando vídeos vencedores do nicho · gerando candidatos · ranqueando
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
          <div className="flex flex-col md:flex-row md:items-center md:justify-between mb-4 gap-2">
            <div className="flex items-center gap-3">
              <h2 className="text-lg">Candidatos</h2>
              <button
                type="button"
                onClick={clearSession}
                className="text-xs text-[var(--muted)] hover:text-[var(--accent)] uppercase tracking-wider"
                style={{ fontFamily: "var(--font-display)" }}
                title="Limpa a transcrição e os candidatos salvos no navegador"
              >
                limpar sessão
              </button>
            </div>
            <div className="text-xs text-[var(--muted)] font-mono">
              JASON consultou {result.rag_outlier_count} vídeos vencedores do nicho como referência
              {!result.model_trained &&
                " · modelo não treinado (sem score)"}
            </div>
          </div>
          <p className="text-sm text-[var(--muted)] mb-4">
            Ordenado pelo previsto.{" "}
            <span style={{ color: "#5BC076" }}>▲ verde</span> = padrão ajudou
            ·{" "}
            <span style={{ color: "var(--accent)" }}>▼ vermelho</span> =
            atrapalhou. Toque em <em>por quê</em> pra abrir.
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
              const isChosen = chosenId !== null && c.suggestion_id === chosenId;
              return (
                <article
                  key={i}
                  className="card"
                  style={isChosen ? { borderColor: "var(--accent)" } : undefined}
                >
                  {/* Linha 1: rank + título (sempre legível) */}
                  <div className="flex items-start gap-3">
                    <div className="font-mono text-sm text-[var(--muted)] shrink-0 pt-0.5">
                      {String(i + 1).padStart(2, "0")}
                    </div>
                    <div className="flex-1 text-sm break-words">{c.title}</div>
                  </div>
                  {/* Linha 2: pill + ações (empilha em mobile) */}
                  <div className="mt-3 flex flex-wrap items-center gap-2 md:gap-3">
                    <span className={`pill ${pillKind} shrink-0`}>
                      {c.multiplier_human ?? "sem score"}
                    </span>
                    {isChosen && (
                      <span
                        className="text-xs uppercase tracking-wider"
                        style={{
                          color: "var(--accent)",
                          fontFamily: "var(--font-display)",
                        }}
                      >
                        ✓ publicada
                      </span>
                    )}
                    <div className="flex-1" />
                    {c.suggestion_id !== null && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleChose(c.suggestion_id!);
                        }}
                        disabled={choosing === c.suggestion_id}
                        className="text-xs uppercase tracking-wider px-3 py-1.5 border transition-colors disabled:opacity-50"
                        style={{
                          fontFamily: "var(--font-display)",
                          borderColor: isChosen
                            ? "var(--accent)"
                            : "var(--border)",
                          color: isChosen ? "var(--accent)" : "var(--muted)",
                          background: "transparent",
                        }}
                      >
                        {choosing === c.suggestion_id
                          ? "..."
                          : isChosen
                          ? "desfazer"
                          : "publiquei essa"}
                      </button>
                    )}
                    <button
                      type="button"
                      className="text-[var(--muted)] hover:text-[var(--text)] font-mono text-xs px-2 py-1.5"
                      onClick={() => setOpenIdx(open ? null : i)}
                    >
                      {open ? "fechar ◢" : "por quê? ▾"}
                    </button>
                  </div>
                  {open && c.contributions.length > 0 && (
                    <div className="mt-4 space-y-3 border-l border-[var(--border)] pl-4">
                      {c.baseline_multiplier !== null && (
                        <div className="text-xs text-[var(--muted)]">
                          <strong className="text-[var(--text)]">
                            Ponto de partida:
                          </strong>{" "}
                          {c.baseline_multiplier.toFixed(2)}x · é o que JASON
                          esperaria de um vídeo {duration}min do canal{" "}
                          <em>antes</em> de olhar pro título. Os ajustes abaixo
                          movem essa nota até o {c.multiplier?.toFixed(2)}x final.
                        </div>
                      )}
                      <div className="space-y-2">
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
                      {c.n_neutral_features > 0 && (
                        <div className="text-xs text-[var(--muted)] pt-1 border-t border-[var(--border)]/50">
                          + {c.n_neutral_features} outras features sem efeito
                          relevante neste título (sentimento, comprimento,
                          clusters etc).
                        </div>
                      )}
                      <div
                        className="text-xs italic"
                        style={{ color: "#7A766C" }}
                      >
                        Estimativa do modelo treinado em ~13k vídeos do nicho —
                        o YouTube nativo (Test &amp; Compare) é o juiz final.
                      </div>
                    </div>
                  )}
                  {open && c.contributions.length === 0 && (
                    <div className="mt-3 text-xs text-[var(--muted)] font-mono">
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
