import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JASON",
  description: "youtube outlier intelligence — @babygiulybaby",
};

const NAV = [
  { href: "/", label: "Início" },
  { href: "/outliers", label: "Outliers" },
  { href: "/avaliar", label: "Avaliar título" },
  { href: "/sugerir", label: "Sugerir" },
  { href: "/thumbs", label: "Thumb" },
];

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen flex flex-col">
        <header className="mast">
          <div className="mast-name">J A S O N</div>
          <div className="mast-sub">youtube outlier intelligence · @babygiulybaby</div>
          <nav className="mt-4 flex gap-6 text-sm">
            {NAV.map((n) => (
              <a key={n.href} href={n.href} className="text-[var(--muted)] hover:text-[var(--text)] uppercase tracking-wider">
                {n.label}
              </a>
            ))}
          </nav>
        </header>
        <main className="flex-1 px-8 py-8 max-w-screen-2xl w-full mx-auto">{children}</main>
        <footer className="border-t border-[var(--border)] px-8 py-4 text-xs text-[var(--muted)] font-mono">
          local instance · backend FastAPI :8000 · frontend Next.js :3000
        </footer>
      </body>
    </html>
  );
}
