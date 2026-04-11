"use server"

import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"

export interface BiomarkerSeries {
  code: string
  name: string
  unit: string | null
  readings: Array<{
    date: string
    value: number
    status: string
  }>
  latest: number
  latestStatus: string
  trend: "improving" | "worsening" | "stable" | "first_reading"
  refLow: number | null
  refHigh: number | null
}

export interface FullTimelineEvent {
  id: string
  event_type: string
  biomarker_name: string | null
  biomarker_code: string | null
  value_numeric: number | null
  value_text: string | null
  unit: string | null
  status: string | null
  source: string
  occurred_at: string
}

export async function getTrendsData(): Promise<{
  series: BiomarkerSeries[]
  timeline: FullTimelineEvent[]
}> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = supabase as any

  const since1y = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString()

  const [eventsRes, timelineRes] = await Promise.all([
    db.from("health_events")
      .select("biomarker_code, biomarker_name, value_numeric, unit, status, reference_low, reference_high, occurred_at")
      .eq("user_id", user.id)
      .eq("event_type", "lab_result")
      .not("value_numeric", "is", null)
      .gte("occurred_at", since1y)
      .order("occurred_at", { ascending: true }),
    db.from("health_events")
      .select("id, event_type, biomarker_name, biomarker_code, value_numeric, value_text, unit, status, source, occurred_at")
      .eq("user_id", user.id)
      .order("occurred_at", { ascending: false })
      .limit(50),
  ])

  const events = (eventsRes.data ?? []) as Array<{
    biomarker_code: string
    biomarker_name: string | null
    value_numeric: number
    unit: string | null
    status: string | null
    reference_low: number | null
    reference_high: number | null
    occurred_at: string
  }>

  // Group by biomarker code
  const byCode = new Map<string, typeof events>()
  for (const e of events) {
    const key = e.biomarker_code ?? e.biomarker_name ?? "unknown"
    if (!byCode.has(key)) byCode.set(key, [])
    byCode.get(key)!.push(e)
  }

  const series: BiomarkerSeries[] = []
  for (const [code, readings] of byCode.entries()) {
    if (readings.length === 0) continue
    const sorted = [...readings].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at))
    const latest = sorted[sorted.length - 1]!
    const earliest = sorted[0]!

    let trend: BiomarkerSeries["trend"] = "first_reading"
    if (sorted.length >= 2 && earliest.value_numeric !== 0) {
      const pct = (latest.value_numeric - earliest.value_numeric) / Math.abs(earliest.value_numeric)
      const isHigh = ["high", "critical"].includes(latest.status ?? "")
      const isLow  = latest.status === "low"
      if (Math.abs(pct) < 0.05) trend = "stable"
      else if (pct > 0) trend = isHigh ? "worsening" : "improving"
      else trend = isLow ? "worsening" : "improving"
    } else if (sorted.length >= 2) {
      trend = "stable"
    }

    series.push({
      code,
      name:         latest.biomarker_name ?? code,
      unit:         latest.unit,
      readings:     sorted.map((r) => ({
        date:   r.occurred_at.split("T")[0]!,
        value:  r.value_numeric,
        status: r.status ?? "normal",
      })),
      latest:       latest.value_numeric,
      latestStatus: latest.status ?? "normal",
      trend,
      refLow:       latest.reference_low,
      refHigh:      latest.reference_high,
    })
  }

  // Sort: critical first, then by reading count desc
  series.sort((a, b) => {
    const score = (s: BiomarkerSeries) =>
      s.latestStatus === "critical" ? 3
      : s.latestStatus === "high" || s.latestStatus === "low" ? 2
      : s.latestStatus === "watch" ? 1 : 0
    return score(b) - score(a) || b.readings.length - a.readings.length
  })

  return {
    series: series.slice(0, 20),
    timeline: (timelineRes.data ?? []) as FullTimelineEvent[],
  }
}
