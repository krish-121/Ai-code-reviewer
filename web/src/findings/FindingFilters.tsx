// Severity chips, category select and the "include suppressed" toggle of the Findings tab.

import type { Category, Severity } from "../lib/types";
import { SeverityMark } from "../components/ui";

export const SEVERITIES: Severity[] = ["high", "medium", "low"];

export interface Filters {
  severities: Set<Severity>;
  category: Category | "all";
  showSuppressed: boolean;
}

interface Props {
  filters: Filters;
  categories: Category[];
  suppressedCount: number;
  onChange: (filters: Filters) => void;
}

export function FindingFilters({ filters, categories, suppressedCount, onChange }: Props) {
  const toggleSeverity = (severity: Severity) => {
    const next = new Set(filters.severities);
    if (next.has(severity)) next.delete(severity);
    else next.add(severity);
    onChange({ ...filters, severities: next });
  };
  return (
    <div className="filters" role="group" aria-label="Filter findings">
      <div className="chips">
        {SEVERITIES.map((severity) => (
          <button
            key={severity}
            className={`chip ${filters.severities.has(severity) ? "on" : ""}`}
            aria-pressed={filters.severities.has(severity)}
            onClick={() => toggleSeverity(severity)}
          >
            <SeverityMark severity={severity} withLabel />
          </button>
        ))}
      </div>
      <select
        value={filters.category}
        onChange={(e) => onChange({ ...filters, category: e.target.value as Category | "all" })}
        aria-label="Category"
      >
        <option value="all">All categories</option>
        {categories.map((category) => (
          <option key={category} value={category}>
            {category}
          </option>
        ))}
      </select>
      <label className="toggle">
        <input
          type="checkbox"
          checked={filters.showSuppressed}
          onChange={(e) => onChange({ ...filters, showSuppressed: e.target.checked })}
        />
        Include suppressed ({suppressedCount})
      </label>
    </div>
  );
}
