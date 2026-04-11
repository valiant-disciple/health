import Link from "next/link"
import { cn } from "@/lib/utils"
import type { TimelineEvent } from "../actions"

const STATUS_STYLES: Record<string, { dot: string; badge: string; row: string }> = {
  normal:   { dot: "bg-green-400",  badge: "bg-green-100 text-green-700",   row: "" },
  watch:    { dot: "bg-yellow-400", badge: "bg-yellow-100 text-yellow-700", row: "bg-yellow-50/40" },
  high:     { dot: "bg-orange-400", badge: "bg-orange-100 text-orange-700", row: "bg-orange-50/30" },
  low:      { dot: "bg-blue-400",   badge: "bg-blue-100 text-blue-700",     row: "bg-blue-50/30" },
  critical: { dot: "bg-red-500",    badge: "bg-red-100 text-red-700",       row: "bg-red-50/40" },
  discuss:  { dot: "bg-orange-400", badge: "bg-orange-100 text-orange-700", row: "bg-orange-50/30" },
}

const SOURCE_LABEL: Record<string, string> = {
  lab_report:   "Lab",
  wearable:     "Wearable",
  self_reported:"Manual",
  medication:   "Medication",
  symptom:      "Symptom",
}

function fmtRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const d = Math.floor(diff / 86400000)
  if (d === 0) return "Today"
  if (d === 1) return "Yesterday"
  if (d < 7)  return `${d}d ago`
  if (d < 30) return `${Math.floor(d / 7)}w ago`
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

export function HealthTimeline({
  events,
  showViewAll = true,
}: {
  events: TimelineEvent[]
  showViewAll?: boolean
}) {
  if (events.length === 0) {
    return (
      <div className="rounded-2xl border-2 border-dashed border-gray-100 py-10 text-center">
        <p className="text-sm text-gray-400">No health events yet.</p>
        <p className="mt-1 text-xs text-gray-300">Upload a lab report or add medications to get started.</p>
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {events.map((e, i) => {
        const s = STATUS_STYLES[e.status ?? "normal"] ?? STATUS_STYLES["normal"]!
        const value = e.value_numeric != null
          ? `${e.value_numeric}${e.unit ? ` ${e.unit}` : ""}`
          : (e.value_text ?? null)

        return (
          <div
            key={e.id}
            className={cn(
              "flex items-center gap-4 rounded-xl px-4 py-3 transition-colors",
              s.row,
              "hover:bg-gray-50"
            )}
          >
            {/* Timeline dot + vertical line */}
            <div className="relative flex flex-col items-center self-stretch pt-1.5">
              <span className={cn("h-2.5 w-2.5 flex-shrink-0 rounded-full", s.dot)} />
              {i < events.length - 1 && (
                <span className="mt-1 flex-1 w-px bg-gray-100" />
              )}
            </div>

            {/* Content */}
            <div className="min-w-0 flex-1 pb-2">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="text-sm font-medium text-gray-900 truncate">
                  {e.biomarker_name ?? e.event_type.replace(/_/g, " ")}
                </span>
                {value && (
                  <span className="text-sm font-semibold tabular-nums text-gray-700">
                    {value}
                  </span>
                )}
                {e.status && e.status !== "normal" && (
                  <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", s.badge)}>
                    {e.status}
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-gray-400">
                <span>{fmtRelative(e.occurred_at)}</span>
                <span>·</span>
                <span>{SOURCE_LABEL[e.source] ?? e.source}</span>
              </div>
            </div>
          </div>
        )
      })}

      {showViewAll && (
        <Link
          href="/trends"
          className="block rounded-xl border border-gray-100 px-4 py-3 text-center text-xs font-medium text-gray-400 hover:bg-gray-50 hover:text-gray-600 transition-colors"
        >
          View full timeline →
        </Link>
      )}
    </div>
  )
}
