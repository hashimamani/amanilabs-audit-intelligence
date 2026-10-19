export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "Undated";
  return new Date(iso).toLocaleString("en-KE", { dateStyle: "medium", timeStyle: "short" });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-KE", { dateStyle: "medium" });
}

export function daysSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000));
}

export function delta(current: number, previous: number | undefined): { text: string; tone: "up" | "down" | "flat" } | null {
  if (previous === undefined) return null;
  const diff = current - previous;
  if (diff === 0) return { text: "no change", tone: "flat" };
  return { text: `${diff > 0 ? "+" : ""}${diff} since last run`, tone: diff > 0 ? "up" : "down" };
}
