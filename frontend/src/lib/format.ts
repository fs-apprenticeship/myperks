export function formatDepartment(department: string): string {
  if (department.toLowerCase() === "hr") return "HR";
  return department.charAt(0).toUpperCase() + department.slice(1);
}

/**
 * Parse a YYYY-MM-DD (or ISO datetime) string as a local date and format it.
 * Avoids the UTC-midnight-to-previous-day shift that `new Date(iso)` causes.
 */
export function formatIsoDate(iso: string): string {
  const [year, month, day] = iso.split("T")[0].split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** Format a YYYY-MM-DD string as "Mon D", e.g. "Jan 1". */
export function formatIsoMonthDay(iso: string): string {
  const [year, month, day] = iso.split("T")[0].split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    day: "numeric",
    month: "short",
  });
}

/** Format a YYYY-MM-DD string as "Mon YYYY", e.g. "Jan 2023". */
export function formatIsoMonthYear(iso: string): string {
  const [year, month, day] = iso.split("T")[0].split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
}

/** Format an ISO datetime as a short relative time, e.g. "5m ago", "3h ago", "2d ago". */
export function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.max(0, Math.round(diffMs / 1000));

  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHour = Math.round(diffMin / 60);
  if (diffHour < 24) return `${diffHour}h ago`;
  const diffDay = Math.round(diffHour / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return formatIsoDate(iso);
}

export function formatRequestType(type: string): string {
  if (type.toLowerCase() === "pto") return "PTO";
  return type.charAt(0).toUpperCase() + type.slice(1);
}
/**
 * For leave requests, return "Jun 6 – Jun 12, 2026" using start/end from body.
 * For reimbursements (no start_date), fall back to the submission date.
 */
export function getRequestDate(item: {
  body: null | string;
  created_at: string;
}): string {
  if (item.body) {
    try {
      const parsed = JSON.parse(item.body) as Record<string, unknown>;
      if (typeof parsed.start_date === "string") {
        const start = formatIsoDate(parsed.start_date);
        if (typeof parsed.end_date === "string") {
          const end = formatIsoDate(parsed.end_date);
          return start === end ? start : `${start} – ${end}`;
        }
        return start;
      }
    } catch {
      // fall through
    }
  }
  return formatIsoDate(item.created_at);
}

export function getRequestDescription(body: null | string): string {
  if (!body) return "—";
  try {
    const parsed = JSON.parse(body) as Record<string, unknown>;
    const text = parsed.reason ?? parsed.description;
    return typeof text === "string" ? text : "—";
  } catch {
    return "—";
  }
}
