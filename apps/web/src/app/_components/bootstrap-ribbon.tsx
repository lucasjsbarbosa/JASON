type Tone = "calibration" | "info";

const TONE_STYLES: Record<Tone, { color: string; symbol: string }> = {
  calibration: { color: "#D4AF37", symbol: "⚠" },
  info: { color: "var(--muted)", symbol: "·" },
};

export function BootstrapRibbon({
  tone = "calibration",
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  const t = TONE_STYLES[tone];
  return (
    <div
      className="text-xs p-3 border border-[var(--border)] flex items-start gap-3"
      style={{ background: "var(--surface-2)", color: "#A8A39A" }}
    >
      <span aria-hidden style={{ color: t.color, fontFamily: "var(--font-display)" }}>
        {t.symbol}
      </span>
      <div className="flex-1">{children}</div>
    </div>
  );
}
