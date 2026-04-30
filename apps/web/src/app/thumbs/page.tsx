"use client";

import { useEffect, useState } from "react";
import {
  type ThemeOption,
  type ThumbSuggestion,
} from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export default function ThumbsPage() {
  const [themes, setThemes] = useState<ThemeOption[]>([]);
  const [themeId, setThemeId] = useState<string>("");
  const [topK, setTopK] = useState(3);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ThumbSuggestion | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/themes`)
      .then((r) => r.json())
      .then(setThemes)
      .catch((e) => setError((e as Error).message));
  }, []);

  async function submit() {
    if (!file) {
      setError("Selecione um arquivo de vídeo.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    const fd = new FormData();
    fd.append("video", file);
    fd.append("top_k", String(topK));
    if (themeId) fd.append("theme_id", themeId);

    try {
      const r = await fetch(`${API_BASE}/api/thumbs/suggest`, {
        method: "POST",
        body: fd,
      });
      if (!r.ok) {
        const text = await r.text().catch(() => "");
        throw new Error(`${r.status}: ${text || r.statusText}`);
      }
      setResult(await r.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8 max-w-5xl">
      <section>
        <h1 className="text-2xl">Sugerir thumbnail</h1>
        <p className="text-sm text-[var(--muted)] mt-2 max-w-3xl">
          Faz upload do vídeo (ou um arquivo prévio). JASON extrai 20 frames,
          descarta os escuros/desfocados, scoreia cada frame restante por
          (a) presença e centralização de rosto e (b) similaridade visual com
          as thumbs que viralizaram no subgênero. Devolve os{" "}
          <span className="font-mono">{topK}</span> melhores frames + paleta
          dominante do tema + sugestão declarativa de texto a sobrepor (você
          edita no Photoshop/Canva).
        </p>
        <p className="text-xs text-[var(--muted)] mt-3 max-w-3xl">
          <strong>Limitação atual:</strong> não detecta efeitos específicos
          (olhos brancos, boca costurada, cutout com glow vermelho) nem texto
          dentro das thumbs do nicho, somente os títulos. OCR/cutout estão
          no roadmap.
        </p>
      </section>

      <section className="card space-y-4">
        <div>
          <label className="block text-sm uppercase tracking-wider mb-2 text-[var(--muted)]">
            Arquivo do vídeo
          </label>
          <input
            type="file"
            accept="video/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm font-mono"
          />
          {file && (
            <div className="text-xs text-[var(--muted)] mt-1 font-mono">
              {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
              Subgênero (opcional, focaliza score + paleta)
            </label>
            <select
              value={themeId}
              onChange={(e) => setThemeId(e.target.value)}
              className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm focus:outline-none focus:border-[var(--accent)]"
            >
              <option value="">Sem filtro (geral do nicho)</option>
              {themes.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label} · {t.n_outliers} outliers
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
              Quantos frames retornar
            </label>
            <input
              type="number"
              value={topK}
              min={1}
              max={6}
              onChange={(e) => setTopK(Number(e.target.value))}
              className="w-full bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm font-mono focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button
            onClick={submit}
            disabled={loading || !file}
            className="px-6 py-2 border border-[var(--accent)] text-[var(--text)] hover:bg-[var(--accent)] hover:text-[var(--bg)] uppercase tracking-wider text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {loading ? "Processando..." : "Sugerir thumb"}
          </button>
          {loading && (
            <span className="text-xs text-[var(--muted)] font-mono">
              ffmpeg → filtros → CLIP scoring → paleta…
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
        <>
          <section>
            <h2 className="text-lg mb-3">Top {result.frames.length} frames</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {result.frames.map((f, i) => (
                <div key={f.filename} className="card">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`${API_BASE}/api/thumbs/frame/${result.job_id}/${f.filename}`}
                    alt={`frame ${i + 1}`}
                    className="w-full"
                  />
                  <div className="mt-3 space-y-1 text-xs font-mono">
                    <div className="flex justify-between">
                      <span className="text-[var(--muted)]">score:</span>
                      <span>{f.score.toFixed(3)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--muted)]">rosto:</span>
                      <span>{f.face_score?.toFixed(3) ?? "·"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[var(--muted)]">similar. outliers:</span>
                      <span>{f.outlier_similarity?.toFixed(3) ?? "·"}</span>
                    </div>
                  </div>
                  <a
                    href={`${API_BASE}/api/thumbs/frame/${result.job_id}/${f.filename}`}
                    download
                    className="block mt-2 text-xs uppercase tracking-wider text-[var(--accent)] hover:text-[var(--text)]"
                  >
                    baixar ↓
                  </a>
                </div>
              ))}
            </div>
          </section>

          <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="card">
              <h3 className="text-base mb-3">Paleta dominante do subgênero</h3>
              {result.palette.length === 0 ? (
                <div className="text-sm text-[var(--muted)]">
                  Selecione um subgênero pra calcular a paleta.
                </div>
              ) : (
                <div className="flex flex-wrap gap-3">
                  {result.palette.map((hex) => (
                    <div key={hex} className="text-center">
                      <div
                        className="w-20 h-16 border border-[var(--border)]"
                        style={{ background: hex }}
                      />
                      <div className="text-[0.7rem] mt-1 font-mono text-[var(--muted)]">
                        {hex}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="card">
              <h3 className="text-base mb-3">Sugestão de texto sobreposto</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-[var(--muted)]">Tem texto?</span>
                  <span>{result.overlay.text_present ? "sim" : "não"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--muted)]">Posição:</span>
                  <span className="font-mono">{result.overlay.text_position}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--muted)]">Cor sugerida:</span>
                  <span className="font-mono">{result.overlay.text_color}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--muted)]">Máximo de palavras:</span>
                  <span className="font-mono">{result.overlay.max_words}</span>
                </div>
                <div className="pt-2 border-t border-[var(--border)]">
                  <div className="text-[var(--muted)] mb-2">Exemplos vencedores:</div>
                  <div className="flex flex-wrap gap-2">
                    {result.overlay.examples.map((ex) => (
                      <span key={ex} className="pill pill-mid">
                        {ex}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="text-xs text-[var(--muted)] font-mono">
            job_id: {result.job_id}
          </section>
        </>
      )}
    </div>
  );
}
