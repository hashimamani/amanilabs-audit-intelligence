import { useEffect, useState } from "react";
import { ShieldCheck, UserPlus } from "lucide-react";
import { ApiError, createUser, listUsers, updateUser } from "../api/client";
import type { Role, UserInfo } from "../api/types";
import { getConfig } from "../config";
import { TableSkeleton } from "../ui/Skeleton";
import { useToast } from "../ui/Toast";

const ROLES: Role[] = ["auditor", "admin"];

export function UsersPage() {
  const toast = useToast();
  const cognito = getConfig().authMode === "cognito";
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("auditor");
  const [creating, setCreating] = useState(false);

  function loadUsers() {
    setLoading(true);
    listUsers()
      .then(setUsers)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load users."))
      .finally(() => setLoading(false));
  }

  useEffect(loadUsers, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await createUser({ email, name, role, ...(cognito ? {} : { password }) });
      toast.success(cognito ? `${name} has been emailed a temporary password.` : `${name} can sign in now.`);
      setEmail("");
      setName("");
      setPassword("");
      setRole("auditor");
      loadUsers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create user.");
    } finally {
      setCreating(false);
    }
  }

  async function change(u: UserInfo, patch: { role?: Role; is_active?: boolean }, done: string) {
    try {
      await updateUser(u.id, patch);
      toast.success(done);
      loadUsers();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Update failed.");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Users</h1>
        <p className="mt-1 text-sm text-slate-500">
          Auditors work cases and run analyses; admins also manage this list. Deactivating someone locks them out on their next request.
        </p>
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</div>}

      <section className="card p-6">
        <h2 className="text-base font-semibold text-slate-900">Add a user</h2>
        {cognito && <p className="mt-1 text-sm text-slate-500">They will be emailed a temporary password and asked to choose their own at first sign-in.</p>}
        <form onSubmit={handleCreate} className={`mt-4 grid grid-cols-1 gap-4 sm:items-end ${cognito ? "sm:grid-cols-4" : "sm:grid-cols-5"}`}>
          <div>
            <label className="text-xs font-medium text-slate-500">Name</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} className="input-field mt-1 block w-full" />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-500">Email</label>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="input-field mt-1 block w-full" />
          </div>
          {!cognito && (
            <div>
              <label className="text-xs font-medium text-slate-500">Initial password</label>
              <input required value={password} onChange={(e) => setPassword(e.target.value)} className="input-field mt-1 block w-full" />
            </div>
          )}
          <div>
            <label className="text-xs font-medium text-slate-500">Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value as Role)} className="input-field mt-1 block w-full">
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={creating} className="btn-primary flex items-center gap-2 py-1.5">
            <UserPlus className="h-4 w-4" />
            {creating ? "Adding…" : "Add user"}
          </button>
        </form>
      </section>

      {loading ? (
        <TableSkeleton rows={4} />
      ) : (
        <div className="card overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Name</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Email</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Role</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500">Status</th>
                <th className="px-4 py-2 text-left font-medium text-slate-500"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-900">{u.name}</td>
                  <td className="px-4 py-3 text-slate-700">{u.email}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {u.role === "admin" && <ShieldCheck className="h-3.5 w-3.5 text-indigo-600" />}
                      <select
                        value={u.role}
                        aria-label={`Role for ${u.name}`}
                        onChange={(e) => void change(u, { role: e.target.value as Role }, `${u.name} is now ${e.target.value}.`)}
                        className={`rounded-md border px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 ${
                          u.role === "admin" ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-slate-300 text-slate-700"
                        }`}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${u.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                      <span className="h-1.5 w-1.5 rounded-full bg-current" />
                      {u.is_active ? "Active" : "Deactivated"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => void change(u, { is_active: !u.is_active }, u.is_active ? `${u.name} has been deactivated.` : `${u.name} has been reactivated.`)}
                      className="text-sm font-medium text-slate-500 hover:text-slate-700"
                    >
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
