import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { listRuns } from "../api/client";
import type { RunSummary } from "../api/types";

const STORAGE_KEY = "audit_intelligence_selected_run";

interface RunValue {
  runs: RunSummary[];
  loading: boolean;
  /** The run every page reads: the chosen one, else the latest that succeeded. */
  selectedRun: RunSummary | null;
  /** The succeeded run before the selected one, for "since last run" deltas. */
  previousRun: RunSummary | null;
  selectRun: (id: number | null) => void;
  refreshRuns: () => Promise<void>;
}

const RunContext = createContext<RunValue | null>(null);

export function RunProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? Number(stored) : null;
    } catch {
      return null;
    }
  });

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await listRuns());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  const selectRun = useCallback((id: number | null) => {
    setSelectedId(id);
    try {
      if (id === null) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, String(id));
    } catch {
      // Storage unavailable: the selection just does not persist.
    }
  }, []);

  const value = useMemo<RunValue>(() => {
    const succeeded = runs.filter((r) => r.status === "succeeded");
    const selected = succeeded.find((r) => r.id === selectedId) ?? succeeded[0] ?? null;
    const previous = selected ? (succeeded.find((r) => r.id < selected.id) ?? null) : null;
    return { runs, loading, selectedRun: selected, previousRun: previous, selectRun, refreshRuns };
  }, [runs, loading, selectedId, selectRun, refreshRuns]);

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>;
}

export function useRun(): RunValue {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error("useRun must be used within RunProvider");
  return ctx;
}
