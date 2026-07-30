import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { FolderSearch, LayoutDashboard, LogOut, ShieldCheck, UploadCloud, Users as UsersIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/cases", label: "Cases", icon: FolderSearch },
  { to: "/upload", label: "Upload & Analyze", icon: UploadCloud },
];

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  const navItems =
    user?.role === "admin" ? [...NAV_ITEMS, { to: "/users", label: "Users", icon: UsersIcon }] : NAV_ITEMS;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white shadow-sm">
        <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-4">
          <span className="flex items-center gap-2 whitespace-nowrap text-lg font-semibold text-slate-900">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white">
              <ShieldCheck className="h-5 w-5" />
            </span>
            Audit Intelligence
          </span>
          {user && (
            <span className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {user.name} &middot; {user.tenant_name}
            </span>
          )}
          <nav className="flex flex-1 items-center gap-1">
            {navItems.map((item) => {
              const active =
                item.to === "/"
                  ? location.pathname === "/"
                  : location.pathname.startsWith(item.to);
              const Icon = item.icon;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    active
                      ? "bg-indigo-50 text-indigo-700"
                      : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-700"
          >
            <LogOut className="h-4 w-4" />
            Log out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
