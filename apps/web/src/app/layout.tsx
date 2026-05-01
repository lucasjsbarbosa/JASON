import type { Metadata } from "next";
import Image from "next/image";
import { Nav } from "./_components/nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "JASON",
  description: "youtube outlier intelligence · @babygiulybaby",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen flex flex-col">
        <header className="mast">
          <div className="flex items-center gap-4">
            <a href="/" className="shrink-0" aria-label="JASON home">
              <Image
                src="/jason-logo.png"
                alt="JASON"
                width={220}
                height={88}
                priority
                className="h-16 w-auto"
              />
            </a>
            <div>
              <div className="mast-sub">youtube outlier intelligence</div>
              <div className="mast-sub" style={{ fontSize: "0.7rem" }}>
                @babygiulybaby
              </div>
            </div>
          </div>
          <Nav />
        </header>
        <main className="flex-1 px-4 md:px-8 py-6 md:py-8 max-w-screen-2xl w-full mx-auto">
          {children}
        </main>
        <footer className="border-t border-[var(--border)] px-4 md:px-8 py-4 text-xs text-[var(--muted)] font-mono">
          jason · local
        </footer>
      </body>
    </html>
  );
}
