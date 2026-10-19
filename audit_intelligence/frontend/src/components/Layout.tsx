import { Link, NavLink, Outlet } from "react-router-dom";
import { BookOpen, FolderSearch, LayoutDashboard, LogOut, PlayCircle, ShieldCheck, UploadCloud, Users as UsersIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { RulesProvider } from "../contexts/RulesContext";
import { RunProvider, useRun } from "../contexts/RunContext";
import { formatDateTime } from "../lib/format";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/cases", label: "Cases", icon: FolderSearch },
  { to: "/upload", label: "Upload & Analyze", icon: UploadCloud },
  { to: "/rules", label: "Rules", icon: BookOpen },
];

function RunSelector() {
  const { runs, selectedRun, selectRun, loading } = useRun();
  const succeeded = runs.filter((r) => r.status === "succeeded");
  if (loading) return <span className="text-sm text-slate-400">Loading runs…</span>;
  if (succeeded.length === 0) return <span className="text-sm text-slate-500">No analysis has been run yet.</span>;
  return (
    <label className="flex items-center gap-2 text-sm text-slate-600">
      <span className="hidden sm:inline">Analysis run</span>
      <select
        aria-label="Analysis run"
        value={selectedRun?.id ?? ""}
        onChange={(e) => selectRun(Number(e.target.value))}
        className="input-field max-w-xs py-1"
      >
        {succeeded.map((r) => (
          <option key={r.id} value={r.id}>
            #{r.id} · {formatDateTime(r.completed_at ?? r.created_at)} · {r.case_count} cases
            {r.dataset_id === "default" ? " · demo data" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

function Shell() {
  const { user, logout } = useAuth();
  const items = user?.role === "admin" ? [...NAV, { to: "/users", label: "Users", icon: UsersIcon }] : NAV;

  const nav = (
    <nav className="flex flex-col gap-0.5">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              }`
            }
          >
            <Icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <Link to="/" className="flex items-center gap-2 px-5 py-5 text-base font-semibold text-slate-900">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white">
            <ShieldCheck className="h-5 w-5" />
          </span>
          Audit Intelligence
        </Link>
        <div className="flex-1 px-3">{nav}</div>
        {user && (
          <div className="border-t border-slate-200 px-5 py-4">
            <div className="truncate text-sm font-medium text-slate-900">{user.name}</div>
            <div className="truncate text-xs text-slate-500">
              {user.tenant_name} · {user.role}
            </div>
            <button onClick={() => void logout()} className="mt-3 flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800">
              <LogOut className="h-3.5 w-3.5" />
              Log out
            </button>
          </div>
        )}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-4 border-b border-slate-200 bg-white px-6 py-3">
          <div className="flex items-center gap-2 md:hidden">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-indigo-600 text-white">
              <ShieldCheck className="h-4 w-4" />
            </span>
            <span className="font-semibold text-slate-900">Audit Intelligence</span>
          </div>
          <RunSelector />
          <div className="flex-1" />
          <Link to="/upload" className="btn-primary flex items-center gap-2 py-1.5">
            <PlayCircle className="h-4 w-4" />
            Run new analysis
          </Link>
          {user && (
            <button onClick={() => void logout()} className="text-sm text-slate-500 hover:text-slate-800 md:hidden">
              Log out
            </button>
          )}
        </header>
        <div className="border-b border-slate-200 bg-white px-3 py-2 md:hidden">{nav}</div>
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function Layout() {
  return (
    <RulesProvider>
      <RunProvider>
        <Shell />
      </RunProvider>
    </RulesProvider>
  );
}
