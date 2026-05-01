"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";

type Item = { href: string; label: string };
type Group = { title: string; items: Item[] };

const GROUPS: Group[] = [
  {
    title: "Entender o nicho",
    items: [
      { href: "/outliers", label: "Outliers" },
      { href: "/palavras", label: "Palavras que bombam" },
      { href: "/comparar", label: "Comparar canais" },
    ],
  },
  {
    title: "Decidir o próximo vídeo",
    items: [
      { href: "/temas", label: "Sugerir tema" },
      { href: "/sugerir", label: "Sugerir título" },
      { href: "/thumbs", label: "Sugerir thumb" },
    ],
  },
  {
    title: "Polir um candidato",
    items: [{ href: "/avaliar", label: "Avaliar título" }],
  },
];

export function Nav() {
  const pathname = usePathname();
  const [openMobile, setOpenMobile] = useState(false);

  const activeGroup = GROUPS.find((g) =>
    g.items.some((it) => it.href === pathname),
  );
  const activeItem = activeGroup?.items.find((it) => it.href === pathname);

  return (
    <>
      {/* Mobile: condensed bar */}
      <div className="md:hidden mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setOpenMobile((v) => !v)}
          aria-expanded={openMobile}
          aria-controls="nav-mobile-panel"
          className="text-xs uppercase tracking-wider px-3 py-2 border border-[var(--border)] hover:border-[var(--accent)] flex items-center gap-2"
          style={{ fontFamily: "var(--font-display)" }}
        >
          <span>menu</span>
          <span aria-hidden>{openMobile ? "▴" : "▾"}</span>
        </button>
        {activeItem && (
          <div className="text-xs text-[var(--muted)] uppercase tracking-wider truncate ml-3">
            {activeGroup?.title} · {activeItem.label}
          </div>
        )}
      </div>

      {openMobile && (
        <div
          id="nav-mobile-panel"
          className="md:hidden mt-3 border border-[var(--border)] divide-y divide-[var(--border)]"
        >
          {GROUPS.map((g) => (
            <div key={g.title} className="p-3">
              <div className="text-[0.65rem] uppercase tracking-widest text-[var(--muted)] mb-2">
                {g.title}
              </div>
              <div className="flex flex-col gap-1">
                {g.items.map((it) => {
                  const active = it.href === pathname;
                  return (
                    <a
                      key={it.href}
                      href={it.href}
                      aria-current={active ? "page" : undefined}
                      onClick={() => setOpenMobile(false)}
                      className={`text-sm py-1.5 px-2 ${
                        active
                          ? "text-[var(--text)]"
                          : "text-[var(--muted)] hover:text-[var(--text)]"
                      }`}
                      style={
                        active
                          ? {
                              borderLeft: "2px solid var(--accent)",
                              paddingLeft: "0.5rem",
                            }
                          : { paddingLeft: "calc(0.5rem + 2px)" }
                      }
                    >
                      {it.label}
                    </a>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Desktop: grouped horizontal nav */}
      <nav className="hidden md:flex mt-5 gap-x-8 gap-y-2 flex-wrap">
        {GROUPS.map((g, gi) => (
          <div key={g.title} className="flex flex-col gap-1">
            <div className="text-[0.65rem] uppercase tracking-widest text-[var(--muted)] opacity-70">
              {g.title}
            </div>
            <div className="flex gap-4">
              {g.items.map((it) => {
                const active = it.href === pathname;
                return (
                  <a
                    key={it.href}
                    href={it.href}
                    aria-current={active ? "page" : undefined}
                    className={`text-sm uppercase tracking-wider transition-colors pb-0.5 ${
                      active
                        ? "text-[var(--text)]"
                        : "text-[var(--muted)] hover:text-[var(--text)]"
                    }`}
                    style={{
                      fontFamily: "var(--font-display)",
                      borderBottom: active
                        ? "1px solid var(--accent)"
                        : "1px solid transparent",
                    }}
                  >
                    {it.label}
                  </a>
                );
              })}
            </div>
            {gi < GROUPS.length - 1 && (
              <span className="hidden md:block" aria-hidden />
            )}
          </div>
        ))}
      </nav>
    </>
  );
}
