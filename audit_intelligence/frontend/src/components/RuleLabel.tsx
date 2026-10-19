import { useRules } from "../contexts/RulesContext";

/** `R001 · Large Withdrawal`, with the rule's summary as the tooltip. */
export function RuleLabel({ id, short = false }: { id: string; short?: boolean }) {
  const { rule } = useRules();
  const info = rule(id);
  return (
    <span title={info?.summary} className="inline-flex items-center gap-1 whitespace-nowrap">
      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{id}</span>
      {!short && info && <span className="text-slate-700">{info.rule_name}</span>}
    </span>
  );
}
