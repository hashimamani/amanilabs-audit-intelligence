import { Link } from "react-router-dom";
import { useRules } from "../contexts/RulesContext";
import { useRun } from "../contexts/RunContext";
import { CardSkeleton } from "../ui/Skeleton";

export function RulesPage() {
  const { rules } = useRules();
  const { selectedRun } = useRun();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">What the engine checks</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Nine explainable rules. Every flag names the rule that raised it and carries the concrete evidence behind it; the AI only ever explains what these rules found, never adds to it.
        </p>
      </div>

      {rules.length === 0 ? (
        <div className="space-y-4">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {rules.map((rule) => {
            const count = selectedRun?.rule_counts[rule.rule_id] ?? 0;
            return (
              <section key={rule.rule_id} className="card flex flex-col p-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{rule.rule_id}</span>
                    <h2 className="mt-1 text-base font-semibold text-slate-900">{rule.rule_name}</h2>
                  </div>
                  {selectedRun && (
                    <Link to={`/cases?rule=${rule.rule_id}`} className="shrink-0 rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100">
                      {count} case{count === 1 ? "" : "s"} in run #{selectedRun.id}
                    </Link>
                  )}
                </div>
                <p className="mt-2 text-sm font-medium text-slate-800">{rule.summary}</p>
                <p className="mt-1 text-sm text-slate-600">{rule.detail}</p>
                <p className="mt-2 text-sm text-slate-600">
                  <span className="font-medium text-slate-800">What it may indicate: </span>
                  {rule.signal}
                </p>
                {rule.thresholds.length > 0 && (
                  <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-slate-100 pt-3 text-xs">
                    {rule.thresholds.map((t) => (
                      <div key={t.key} className="flex justify-between gap-2">
                        <dt className="text-slate-500">{t.label}</dt>
                        <dd className="font-medium text-slate-800">{t.value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
