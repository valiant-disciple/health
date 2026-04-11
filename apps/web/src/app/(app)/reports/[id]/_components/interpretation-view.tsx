import { cn } from "@/lib/utils"
import type {
  Interpretation,
  InterpretFinding,
  DietarySuggestion,
  LifestyleSuggestion,
  DrugNutrientFlag,
  DoctorItem,
} from "../../actions"

// ─── Status styles ────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, { card: string; badge: string; bar: string }> = {
  normal:   { card: "border-green-100  bg-green-50/40",  badge: "bg-green-100 text-green-700",   bar: "bg-green-400" },
  watch:    { card: "border-yellow-100 bg-yellow-50/40", badge: "bg-yellow-100 text-yellow-700", bar: "bg-yellow-400" },
  high:     { card: "border-orange-100 bg-orange-50/40", badge: "bg-orange-100 text-orange-700", bar: "bg-orange-400" },
  low:      { card: "border-blue-100   bg-blue-50/30",   badge: "bg-blue-100 text-blue-700",     bar: "bg-blue-400" },
  critical: { card: "border-red-200    bg-red-50/60",    badge: "bg-red-100 text-red-700 font-bold", bar: "bg-red-500" },
  discuss:  { card: "border-orange-100 bg-orange-50/40", badge: "bg-orange-100 text-orange-700", bar: "bg-orange-400" },
}

const URGENCY: Record<string, { class: string; icon: string }> = {
  routine: { class: "border-gray-200 bg-gray-50 text-gray-700",        icon: "📋" },
  soon:    { class: "border-yellow-200 bg-yellow-50 text-yellow-800",  icon: "⚠️" },
  urgent:  { class: "border-red-200 bg-red-50 text-red-800",           icon: "🚨" },
}

const SEVERITY_COLORS: Record<string, string> = {
  major:    "text-red-600 font-semibold",
  moderate: "text-orange-600",
  minor:    "text-gray-500",
}

const TREND_ICON: Record<string, string> = {
  improving:     "↗ Improving",
  worsening:     "↘ Worsening",
  stable:        "→ Stable",
  first_reading: "• First reading",
}

const PRIORITY_DOT: Record<string, string> = {
  high:   "bg-red-400",
  medium: "bg-yellow-400",
  low:    "bg-gray-300",
}

function s(status: string) {
  return STATUS_STYLES[status] ?? STATUS_STYLES["normal"]!
}

// ─── Sub-sections ─────────────────────────────────────────────────────────────

function SectionHeader({ title, count, icon }: { title: string; count?: number; icon: string }) {
  return (
    <div className="mb-4 flex items-center gap-2">
      <span className="text-lg">{icon}</span>
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {count != null && (
        <span className="ml-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
          {count}
        </span>
      )}
    </div>
  )
}

function FindingCard({
  f,
  history,
}: {
  f: InterpretFinding
  history?: Array<{ date: string; value: number; status: string }> | undefined
}) {
  const styles = s(f.status)
  return (
    <div className={cn("rounded-2xl border p-4", styles.card)}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-gray-900">{f.name}</span>
            <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", styles.badge)}>
              {f.value}
            </span>
            {f.status !== "normal" && (
              <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", styles.badge)}>
                {f.status}
              </span>
            )}
          </div>
          {f.trend && (
            <p className="mt-0.5 text-xs text-gray-400">{TREND_ICON[f.trend] ?? f.trend}</p>
          )}
        </div>
        {history && history.length >= 2 && (
          // Inline tiny sparkline
          <div className="w-20 flex-shrink-0 opacity-80">
            <InlineSparkline data={history} status={f.status} />
          </div>
        )}
      </div>
      <p className="mt-2 text-sm leading-relaxed text-gray-700">{f.explanation}</p>
      {f.previous_value && f.previous_date && (
        <p className="mt-1 text-xs text-gray-400">
          Previous: {f.previous_value} on {f.previous_date}
        </p>
      )}
    </div>
  )
}

// Tiny inline SVG sparkline — no recharts needed for these tiny ones
function InlineSparkline({
  data,
  status,
}: {
  data: Array<{ value: number }>
  status: string
}) {
  const values = data.map((d) => d.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const W = 80
  const H = 28
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * W
      const y = H - ((v - min) / range) * H
      return `${x},${y}`
    })
    .join(" ")
  const color =
    status === "critical" ? "#ef4444"
    : status === "high"   ? "#f97316"
    : status === "low"    ? "#3b82f6"
    : "#22c55e"

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="overflow-visible">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {/* Last dot */}
      {values.length > 0 && (
        <circle
          cx={(((values.length - 1) / (values.length - 1)) * W).toString()}
          cy={(H - ((values[values.length - 1]! - min) / range) * H).toString()}
          r="2.5"
          fill={color}
        />
      )}
    </svg>
  )
}

function DietaryCard({ d }: { d: DietarySuggestion }) {
  const dot = PRIORITY_DOT[d.priority] ?? PRIORITY_DOT["low"]!
  return (
    <div className="flex gap-3 rounded-xl border border-gray-100 bg-white p-4">
      <span className={cn("mt-1.5 h-2 w-2 flex-shrink-0 rounded-full", dot)} />
      <div>
        <p className="text-sm font-semibold text-gray-900">
          <span className="mr-1 capitalize text-gray-400">{d.category}:</span>
          {d.suggestion}
        </p>
        <p className="mt-0.5 text-xs text-gray-500">{d.mechanism}</p>
        {d.foods.length > 0 && (
          <p className="mt-1 text-xs text-gray-400">
            e.g. {d.foods.slice(0, 3).join(", ")}
          </p>
        )}
      </div>
    </div>
  )
}

function LifestyleCard({ l }: { l: LifestyleSuggestion }) {
  const dot = PRIORITY_DOT[l.priority] ?? PRIORITY_DOT["low"]!
  return (
    <div className="flex gap-3 rounded-xl border border-gray-100 bg-white p-4">
      <span className={cn("mt-1.5 h-2 w-2 flex-shrink-0 rounded-full", dot)} />
      <div>
        <p className="text-sm font-semibold text-gray-900">{l.suggestion}</p>
        <p className="mt-0.5 text-xs text-gray-500 capitalize">{l.category} · {l.mechanism}</p>
      </div>
    </div>
  )
}

function DrugFlag({ f }: { f: DrugNutrientFlag }) {
  return (
    <div className="rounded-xl border border-yellow-100 bg-yellow-50 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-gray-900">
            {f.medication} depletes <span className="text-yellow-700">{f.depletes}</span>
          </p>
          <p className="mt-0.5 text-xs text-gray-600">{f.interaction}</p>
          <p className="mt-1 text-xs text-gray-500">{f.suggestion}</p>
        </div>
        <span className={cn("flex-shrink-0 text-xs", SEVERITY_COLORS[f.severity] ?? "text-gray-500")}>
          {f.severity}
        </span>
      </div>
    </div>
  )
}

function DoctorCard({ item }: { item: DoctorItem }) {
  const u = URGENCY[item.urgency] ?? URGENCY["routine"]!
  return (
    <div className={cn("flex gap-3 rounded-xl border px-4 py-3", u.class)}>
      <span className="text-base">{u.icon}</span>
      <div>
        <p className="text-sm font-semibold">{item.finding}</p>
        <p className="mt-0.5 text-xs opacity-80">{item.reason}</p>
      </div>
    </div>
  )
}

// ─── Main view ────────────────────────────────────────────────────────────────

export function InterpretationView({
  interpretation,
  biomarkerHistory,
}: {
  interpretation: Interpretation
  biomarkerHistory: Record<string, Array<{ date: string; value: number; status: string }>>
}) {
  const { summary, key_findings, dietary_suggestions, lifestyle_suggestions, drug_nutrient_flags, discuss_with_doctor } = interpretation

  const urgentItems = discuss_with_doctor.filter((d) => d.urgency === "urgent" || d.urgency === "soon")
  const abnormalFindings = key_findings.filter((f) => f.status !== "normal")

  return (
    <div className="space-y-8">
      {/* Summary banner */}
      <div className="rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50 to-indigo-50 p-6">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-blue-100">
            <svg className="h-5 w-5 text-blue-600" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-500">AI Summary</p>
            <p className="mt-1 text-sm leading-relaxed text-gray-800">{summary}</p>
          </div>
        </div>

        {/* Quick stats */}
        <div className="mt-4 flex flex-wrap gap-3 border-t border-blue-100 pt-4">
          <Chip label={`${key_findings.length} results reviewed`} />
          {abnormalFindings.length > 0 && (
            <Chip label={`${abnormalFindings.length} abnormal`} accent="orange" />
          )}
          {discuss_with_doctor.length > 0 && (
            <Chip label={`${discuss_with_doctor.length} to discuss with doctor`} accent={urgentItems.length > 0 ? "red" : "yellow"} />
          )}
          {drug_nutrient_flags.length > 0 && (
            <Chip label={`${drug_nutrient_flags.length} drug-nutrient flag${drug_nutrient_flags.length === 1 ? "" : "s"}`} accent="yellow" />
          )}
        </div>
      </div>

      {/* Discuss with doctor — show first if urgent */}
      {discuss_with_doctor.length > 0 && (
        <section>
          <SectionHeader title="Discuss with your doctor" count={discuss_with_doctor.length} icon="🩺" />
          <div className="space-y-2">
            {discuss_with_doctor
              .sort((a, b) => {
                const rank: Record<string, number> = { urgent: 0, soon: 1, routine: 2 }
                return (rank[a.urgency] ?? 2) - (rank[b.urgency] ?? 2)
              })
              .map((item, i) => <DoctorCard key={i} item={item} />)}
          </div>
        </section>
      )}

      {/* Key findings */}
      {key_findings.length > 0 && (
        <section>
          <SectionHeader title="Key findings" count={key_findings.length} icon="🔬" />
          <div className="grid gap-3 sm:grid-cols-2">
            {key_findings.map((f, i) => {
              const hist = biomarkerHistory[f.loinc]
              return <FindingCard key={i} f={f} history={hist} />
            })}
          </div>
        </section>
      )}

      {/* Drug-nutrient flags */}
      {drug_nutrient_flags.length > 0 && (
        <section>
          <SectionHeader title="Medication interactions" count={drug_nutrient_flags.length} icon="💊" />
          <div className="space-y-3">
            {drug_nutrient_flags.map((f, i) => <DrugFlag key={i} f={f} />)}
          </div>
        </section>
      )}

      {/* Dietary suggestions */}
      {dietary_suggestions.length > 0 && (
        <section>
          <SectionHeader title="Dietary suggestions" count={dietary_suggestions.length} icon="🥗" />
          <div className="grid gap-3 sm:grid-cols-2">
            {dietary_suggestions.map((d, i) => <DietaryCard key={i} d={d} />)}
          </div>
        </section>
      )}

      {/* Lifestyle suggestions */}
      {lifestyle_suggestions.length > 0 && (
        <section>
          <SectionHeader title="Lifestyle suggestions" count={lifestyle_suggestions.length} icon="🏃" />
          <div className="grid gap-3 sm:grid-cols-2">
            {lifestyle_suggestions.map((l, i) => <LifestyleCard key={i} l={l} />)}
          </div>
        </section>
      )}

      <p className="text-center text-xs text-gray-300">
        AI interpretation · health is not a medical device · always consult your physician
      </p>
    </div>
  )
}

function Chip({ label, accent }: { label: string; accent?: "orange" | "red" | "yellow" }) {
  return (
    <span className={cn(
      "rounded-full px-2.5 py-1 text-xs font-medium",
      accent === "red"    ? "bg-red-100 text-red-700" :
      accent === "orange" ? "bg-orange-100 text-orange-700" :
      accent === "yellow" ? "bg-yellow-100 text-yellow-700" :
      "bg-white/70 text-gray-600"
    )}>
      {label}
    </span>
  )
}
