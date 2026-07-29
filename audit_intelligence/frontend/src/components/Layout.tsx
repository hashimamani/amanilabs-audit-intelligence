import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { getCurrentTenant } from "../api/client";
import type { TenantInfo } from "../api/types";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/cases", label: "Cases" },
  { to: "/upload", label: "Upload & Analyze" },
];

export function Layout() {
  const location = useLocation();
  const [tenant, setTenant] = useState<TenantInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCurrentTenant()
      .then((info) => {
        if (!cancelled) setTenant(info);
      })
      .catch(() => {
        // Nav bar degrades gracefully to no tenant badge (e.g. an invalid
        // key never showed one before this either - not worth an error UI).
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-4">
          <span className="text-lg font-semibold text-slate-900">
            Audit Intelligence
          </span>
          {tenant && (
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {tenant.name}
            </span>
          )}
          <nav className="flex gap-4">
            {NAV_ITEMS.map((item) => {
              const active =
                item.to === "/"
                  ? location.pathname === "/"
                  : location.pathname.startsWith(item.to);
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`text-sm font-medium ${
                    active ? "text-slate-900" : "text-slate-500 hover:text-slate-700"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
