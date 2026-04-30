// Tiny fetch wrapper pointing at the FastAPI backend.

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`API ${path} → ${r.status}: ${text || r.statusText}`);
  }
  return r.json() as Promise<T>;
}

// --- response types (mirror src/jason/api/main.py) ----------------------

export type OutlierVideo = {
  id: string;
  title: string;
  channel: string;
  percentile: number | null;
  multiplier: number | null;
  views: number | null;
  thumbnail_url: string | null;
  theme_label: string | null;
  franchise_label: string | null;
  multiplier_human: string | null;
  percentile_human: string | null;
};

export type OwnMetrics = {
  long_videos: number;
  last_upload: string | null;
  top_multiplier: number | null;
  soft_outliers: number;
  top_multiplier_human: string | null;
};

export type ScoreContribution = {
  feature: string;
  label: string;
  value: string;
  contribution: number;
  direction: "up" | "down";
  verb: string;
  color: string;
};

export type ScoreResponse = {
  multiplier: number;
  log_multiplier: number;
  multiplier_human: string;
  contributions: ScoreContribution[];
};

export type PackagingGapRow = {
  feature: string;
  own_pct: number;
  niche_pct: number;
  diff_pp: number;
};

export type ThemeCoverage = {
  theme: string;
  own_n: number;
  own_avg_mult: number | null;
  own_top_mult: number | null;
  niche_n: number | null;
  niche_avg_mult: number | null;
  niche_top_mult: number | null;
};
