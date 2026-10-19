import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { listRules } from "../api/client";
import type { RuleInfo } from "../api/types";

interface RulesValue {
  rules: RuleInfo[];
  ruleName: (id: string) => string;
  rule: (id: string) => RuleInfo | undefined;
}

const RulesContext = createContext<RulesValue | null>(null);

export function RulesProvider({ children }: { children: ReactNode }) {
  const [rules, setRules] = useState<RuleInfo[]>([]);
  useEffect(() => {
    listRules().then(setRules).catch(() => setRules([]));
  }, []);
  const value = useMemo<RulesValue>(() => {
    const byId = new Map(rules.map((r) => [r.rule_id, r]));
    return {
      rules,
      rule: (id) => byId.get(id),
      ruleName: (id) => byId.get(id)?.rule_name ?? id,
    };
  }, [rules]);
  return <RulesContext.Provider value={value}>{children}</RulesContext.Provider>;
}

export function useRules(): RulesValue {
  const ctx = useContext(RulesContext);
  if (!ctx) throw new Error("useRules must be used within RulesProvider");
  return ctx;
}
