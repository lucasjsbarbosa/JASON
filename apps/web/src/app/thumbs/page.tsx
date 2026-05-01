"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  type ThemeOption,
  type ThumbSuggestion,
} from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const norm = (s: string) =>
  s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

export default function ThumbsPage() {
  const [themes, setThemes] = useState<ThemeOption[]>([]);
  const [themeId, setThemeId] = useState<string>("");
  const [themeQuery, setThemeQuery] = useState<string>("");
  const [themeOpen, setThemeOpen] = useState(false);
  const [topK, setTopK] = useState(3);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ThumbSuggestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const themeBoxRef = useRef<HTMLDivElement | null>(null);

  const filteredThemes = useMemo(() => {
    if (!themeQuery.trim()) return themes;
    const q = norm(themeQuery);
    return themes.filter((t) => norm(t.label).includes(q));
  }, [themes, themeQuery]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (
        themeBoxRef.current &&
        !themeBoxRef.current.contains(e.target as Node)
      ) {
        setThemeOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function pickTheme(t: ThemeOption | null) {
    if (t === null) {
      setThemeId("");
      setThemeQuery("");
    } else {
      setThemeId(String(t.id));
      setThemeQuery(t.label);
    }
    setThemeOpen(false);
  }

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
        const body = await r.text().catch(() => "");
        let msg = body || r.statusText;
        try {
          const j = JSON.parse(body);
          msg = j.detail || msg;
        } catch {}
        throw new Error(`${r.status} · ${msg}`);
      }
      setResult(await r.json());
    } catch (e) {
      setError((e as Error).message);
      // Garantir que o erro fica visível no topo
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8 max-w-5xl">
      {error && (
        <div className="card border-2 border-[var(--accent)] bg-[var(--accent)]/10 p-4">
          <div className="text-xs uppercase tracking-wider text-[var(--accent)] mb-2">
            Erro
          </div>
          <div className="text-sm font-mono whitespace-pre-wrap break-words">
            {error}
          </div>
          {error.includes("ffprobe") || error.includes("ffmpeg") ? (
            <div className="text-xs mt-3 text-[var(--muted)]">
              ffmpeg não está instalado. No terminal do WSL: <code className="text-[var(--accent)]">sudo apt install -y ffmpeg</code>
            </div>
          ) : null}
        </div>
      )}

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
          <div ref={themeBoxRef} className="relative">
            <label className="block text-xs uppercase tracking-wider mb-1 text-[var(--muted)]">
              Subgênero (opcional, focaliza score + paleta)
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={themeQuery}
                placeholder="Sem filtro · digite pra buscar (ex: slasher, possessão)"
                onFocus={() => setThemeOpen(true)}
                onChange={(e) => {
                  setThemeQuery(e.target.value);
                  setThemeOpen(true);
                  if (!e.target.value) setThemeId("");
                }}
                className="flex-1 bg-[var(--surface-2)] border border-[var(--border)] p-2 text-sm focus:outline-none focus:border-[var(--accent)]"
              />
              {themeQuery && (
                <button
                  type="button"
                  onClick={() => pickTheme(null)}
                  className="px-3 border border-[var(--border)] text-xs text-[var(--muted)] hover:text-[var(--accent)]"
                  title="Limpar filtro"
                >
                  ×
                </button>
              )}
            </div>
            {themeOpen && (
              <div className="absolute z-10 mt-1 w-full max-h-80 overflow-auto bg-[var(--surface-2)] border border-[var(--border)] shadow-lg">
                <button
                  type="button"
                  onClick={() => pickTheme(null)}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-[var(--surface-3)] border-b border-[var(--border)] text-[var(--muted)]"
                >
                  Sem filtro (geral do nicho)
                </button>
                {filteredThemes.length === 0 ? (
                  <div className="px-3 py-3 text-sm text-[var(--muted)]">
                    Nada encontrado pra "{themeQuery}".
                  </div>
                ) : (
                  filteredThemes.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => pickTheme(t)}
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-[var(--surface-3)] flex justify-between gap-3 ${
                        String(t.id) === themeId
                          ? "bg-[var(--surface-3)]"
                          : ""
                      }`}
                    >
                      <span>{t.label}</span>
                      <span className="text-xs font-mono text-[var(--muted)] shrink-0">
                        {t.n_outliers} outliers
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
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

          <details className="text-xs text-[var(--muted)]">
            <summary className="cursor-pointer hover:text-[var(--text)] uppercase tracking-wider"
              style={{ fontFamily: "var(--font-display)" }}>
              ver detalhes técnicos
            </summary>
            <div className="mt-2 font-mono pl-4">
              identificador desta análise: {result.job_id}
            </div>
          </details>
        </>
      )}
    </div>
  );
}
