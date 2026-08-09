import {
  Bar,
  BarChart as RechartsBarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartDatapoint } from "../api/types";

// Severity already has established, meaningful colors elsewhere in the app
// (SeverityBadge.tsx) - reuse them here rather than a generic categorical
// palette, so a severity breakdown reads consistently everywhere it appears.
const SEVERITY_COLORS: Record<string, string> = {
  Critical: "#ef4444", // red-500
  High: "#f97316", // orange-500
  Medium: "#f59e0b", // amber-500
  Low: "#94a3b8", // slate-400
};
const DEFAULT_COLOR = "#6366f1"; // indigo-500, the app's signature accent

function colorFor(label: string): string {
  return SEVERITY_COLORS[label] ?? DEFAULT_COLOR;
}

export function BarChart({ data }: { data: ChartDatapoint[] }) {
  if (data.length === 0) return <p className="text-sm text-slate-400">No data.</p>;
  return (
    <div style={{ width: "100%", height: Math.max(160, data.length * 40) }}>
      <ResponsiveContainer>
        <RechartsBarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
          <CartesianGrid horizontal={false} stroke="#e2e8f0" />
          <XAxis
            type="number"
            allowDecimals={false}
            tick={{ fontSize: 12, fill: "#64748b" }}
            axisLine={{ stroke: "#e2e8f0" }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={110}
            tick={{ fontSize: 12, fill: "#334155" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip cursor={{ fill: "#f1f5f9" }} contentStyle={{ borderRadius: 8, borderColor: "#e2e8f0", fontSize: 12 }} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={28}>
            {data.map((d) => (
              <Cell key={d.label} fill={colorFor(d.label)} />
            ))}
          </Bar>
        </RechartsBarChart>
      </ResponsiveContainer>
    </div>
  );
}
