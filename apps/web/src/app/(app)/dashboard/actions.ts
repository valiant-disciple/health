"use server"

import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"

export interface DashboardStats {
  reportsTotal: number
  reportsPending: number
  activeMeds: number
  abnormalResults: number
  criticalResults: number
  lastReportDate: string | null
}

export interface TimelineEvent {
  id: string
  event_type: string
  biomarker_name: string | null
  value_numeric: number | null
  value_text: string | null
  unit: string | null
  status: string | null
  source: string
  occurred_at: string
}

export interface ProfileData {
  display_name: string | null
  onboarding_complete: boolean
}

export async function getDashboardData(): Promise<{
  stats: DashboardStats
  timeline: TimelineEvent[]
  profile: ProfileData
}> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = supabase as any

  const since90d = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString()

  const [profileRes, reportsRes, medsRes, abnormalRes, timelineRes] = await Promise.all([
    db.from("user_profile")
      .select("display_name, onboarding_complete")
      .eq("id", user.id)
      .single(),
    db.from("lab_reports")
      .select("id, processing_status, created_at")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false }),
    db.from("medications")
      .select("id")
      .eq("user_id", user.id)
      .eq("status", "active")
      .is("valid_until", null),
    db.from("health_events")
      .select("id, status")
      .eq("user_id", user.id)
      .neq("status", "normal")
      .gte("occurred_at", since90d),
    db.from("health_events")
      .select("id, event_type, biomarker_name, value_numeric, value_text, unit, status, source, occurred_at")
      .eq("user_id", user.id)
      .order("occurred_at", { ascending: false })
      .limit(15),
  ])

  const reports = (reportsRes.data ?? []) as Array<{ id: string; processing_status: string; created_at: string }>
  const abnormal = (abnormalRes.data ?? []) as Array<{ id: string; status: string }>

  const stats: DashboardStats = {
    reportsTotal:    reports.length,
    reportsPending:  reports.filter((r) => r.processing_status === "pending" || r.processing_status === "processing").length,
    activeMeds:      (medsRes.data ?? []).length,
    abnormalResults: abnormal.filter((e) => e.status !== "critical").length,
    criticalResults: abnormal.filter((e) => e.status === "critical").length,
    lastReportDate:  reports[0]?.created_at ?? null,
  }

  return {
    stats,
    timeline: (timelineRes.data ?? []) as TimelineEvent[],
    profile:  (profileRes.data ?? { display_name: null, onboarding_complete: false }) as ProfileData,
  }
}
