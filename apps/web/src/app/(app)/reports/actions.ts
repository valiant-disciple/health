"use server"

import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import { revalidatePath } from "next/cache"

const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://localhost:8000"

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ReportRow {
  id: string
  file_name: string | null
  report_date: string | null
  lab_name: string | null
  processing_status: string
  ocr_raw: string | null
  created_at: string
}

// ─── Interpretation types ─────────────────────────────────────────────────────

export interface InterpretFinding {
  loinc: string
  name: string
  value: string
  status: string
  explanation: string
  trend: string
  previous_value: string | null
  previous_date: string | null
}

export interface DietarySuggestion {
  category: string
  suggestion: string
  mechanism: string
  foods: string[]
  priority: string
}

export interface LifestyleSuggestion {
  category: string
  suggestion: string
  mechanism: string
  priority: string
}

export interface DrugNutrientFlag {
  medication: string
  depletes: string
  interaction: string
  suggestion: string
  severity: string
}

export interface DoctorItem {
  finding: string
  reason: string
  urgency: string
}

export interface Interpretation {
  summary: string
  key_findings: InterpretFinding[]
  dietary_suggestions: DietarySuggestion[]
  lifestyle_suggestions: LifestyleSuggestion[]
  drug_nutrient_flags: DrugNutrientFlag[]
  discuss_with_doctor: DoctorItem[]
}

export interface LabResultRow {
  id: string
  loinc_code: string
  loinc_name: string
  display_name: string | null
  value_numeric: number | null
  value_text: string | null
  unit: string | null
  ref_range_low: number | null
  ref_range_high: number | null
  ref_range_text: string | null
  status: string | null
  flag: string | null
  occurred_at: string
}

// ─── Upload ───────────────────────────────────────────────────────────────────

export async function uploadLabReport(
  _prevState: { error?: string } | null,
  formData: FormData
): Promise<{ error?: string }> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const file = formData.get("file") as File | null
  if (!file || !file.name) return { error: "No file selected." }
  if (file.type !== "application/pdf") return { error: "Only PDF files are accepted." }
  if (file.size > 20 * 1024 * 1024) return { error: "File must be under 20 MB." }

  // Build storage path
  const timestamp = Date.now()
  const safeName = file.name.replace(/[^a-zA-Z0-9.\-_]/g, "_")
  const filePath = `${user.id}/${timestamp}_${safeName}`

  // Upload to Supabase Storage
  const fileBuffer = await file.arrayBuffer()
  const { error: storageError } = await supabase.storage
    .from("lab-reports")
    .upload(filePath, fileBuffer, {
      contentType: "application/pdf",
      upsert: false,
    })

  if (storageError) return { error: `Upload failed: ${storageError.message}` }

  // Create DB record
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { data: report, error: dbError } = await (supabase as any)
    .from("lab_reports")
    .insert({
      user_id: user.id,
      file_path: filePath,
      file_name: file.name,
      processing_status: "pending",
    })
    .select("id")
    .single()

  if (dbError) return { error: dbError.message }

  const reportId = (report as { id: string }).id

  // Trigger OCR — fire and forget (3s timeout so we don't block the redirect)
  void fetch(`${AI_SERVICE_URL}/ocr/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ report_id: reportId, user_id: user.id, file_path: filePath }),
    signal: AbortSignal.timeout(3000),
  }).catch((e: unknown) =>
    console.error("[OCR trigger]", e instanceof Error ? e.message : e)
  )

  revalidatePath("/reports")
  redirect("/reports")
}

// ─── Queries ──────────────────────────────────────────────────────────────────

export async function getReports(): Promise<ReportRow[]> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { data } = await (supabase as any)
    .from("lab_reports")
    .select("id, file_name, report_date, lab_name, processing_status, created_at")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false })
    .limit(50)

  return (data ?? []) as ReportRow[]
}

export async function getReport(reportId: string): Promise<{
  report: ReportRow | null
  results: LabResultRow[]
  interpretation: Interpretation | null
  biomarkerHistory: Record<string, Array<{ date: string; value: number; status: string }>>
}> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = supabase as any

  const [reportRes, resultsRes] = await Promise.all([
    db
      .from("lab_reports")
      .select("id, file_name, report_date, lab_name, processing_status, ocr_raw, created_at")
      .eq("id", reportId)
      .eq("user_id", user.id)
      .single(),
    db
      .from("lab_results")
      .select(
        "id, loinc_code, loinc_name, display_name, value_numeric, value_text, unit, ref_range_low, ref_range_high, ref_range_text, status, flag, occurred_at"
      )
      .eq("report_id", reportId)
      .eq("user_id", user.id)
      .order("loinc_name"),
  ])

  const report = reportRes.data as ReportRow | null
  const results = (resultsRes.data ?? []) as LabResultRow[]

  // Parse cached interpretation from ocr_raw
  let interpretation: Interpretation | null = null
  if (report?.ocr_raw) {
    try {
      const raw = JSON.parse(report.ocr_raw) as Record<string, unknown>
      if (raw.interpretation) interpretation = raw.interpretation as Interpretation
    } catch { /* ignore */ }
  }

  // Fetch trend history for each biomarker in this report (last 12 months)
  const loinc_codes = [...new Set(results.map((r) => r.loinc_code).filter(Boolean))]
  let biomarkerHistory: Record<string, Array<{ date: string; value: number; status: string }>> = {}

  if (loinc_codes.length > 0) {
    const since1y = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString()
    const { data: events } = await db
      .from("health_events")
      .select("biomarker_code, value_numeric, status, occurred_at")
      .eq("user_id", user.id)
      .in("biomarker_code", loinc_codes)
      .not("value_numeric", "is", null)
      .gte("occurred_at", since1y)
      .order("occurred_at")

    for (const e of (events ?? []) as Array<{ biomarker_code: string; value_numeric: number; status: string; occurred_at: string }>) {
      const key = e.biomarker_code
      if (!biomarkerHistory[key]) biomarkerHistory[key] = []
      biomarkerHistory[key]!.push({
        date:   e.occurred_at.split("T")[0]!,
        value:  e.value_numeric,
        status: e.status ?? "normal",
      })
    }
  }

  return { report, results, interpretation, biomarkerHistory }
}

// ─── Interpret ────────────────────────────────────────────────────────────────

export async function requestInterpretation(
  reportId: string
): Promise<{ interpretation?: Interpretation; error?: string }> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const res = await fetch(`${AI_SERVICE_URL}/interpret/report`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": user.id,
    },
    body: JSON.stringify({ user_id: user.id, report_id: reportId }),
    signal: AbortSignal.timeout(180000),
  })

  if (!res.ok) {
    const txt = await res.text().catch(() => "")
    return { error: `Interpretation failed (${res.status})${txt ? `: ${txt}` : ""}` }
  }

  const data = (await res.json()) as { interpretation: Interpretation }

  // Cache interpretation alongside ocr data
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = supabase as any
  const { data: existing } = await db.from("lab_reports").select("ocr_raw").eq("id", reportId).single()
  let merged: Record<string, unknown> = {}
  try { merged = JSON.parse((existing as { ocr_raw: string | null } | null)?.ocr_raw ?? "{}") } catch { /**/ }
  merged.interpretation = data.interpretation
  await db.from("lab_reports").update({ ocr_raw: JSON.stringify(merged) }).eq("id", reportId)

  revalidatePath(`/reports/${reportId}`)
  return { interpretation: data.interpretation }
}
