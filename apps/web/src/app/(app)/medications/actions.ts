"use server"

import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import { revalidatePath } from "next/cache"

// ─── Types ────────────────────────────────────────────────────────────────────

export interface MedRow {
  id: string
  name: string
  rxnorm_code: string | null
  generic_name: string | null
  brand_name: string | null
  dose_amount: number | null
  dose_unit: string | null
  frequency: string | null
  route: string | null
  timing: string | null
  indication: string | null
  prescribing_provider: string | null
  started_date: string
  stopped_date: string | null
  status: string
  notes: string | null
}

export interface RxNormSuggestion {
  rxcui: string
  name: string
  synonym: string | null
}

// ─── RxNorm lookup (server-side, NIH API — no key required) ──────────────────

export async function searchRxNorm(query: string): Promise<RxNormSuggestion[]> {
  if (!query || query.length < 2) return []

  try {
    const url = `https://rxnav.nlm.nih.gov/REST/drugs.json?name=${encodeURIComponent(query)}`
    const res = await fetch(url, {
      next: { revalidate: 3600 }, // cache 1 hour
      signal: AbortSignal.timeout(5000),
    })
    if (!res.ok) return []

    const data = (await res.json()) as {
      drugGroup?: {
        conceptGroup?: Array<{
          tty?: string
          conceptProperties?: Array<{ rxcui: string; name: string; synonym: string }>
        }>
      }
    }

    const groups = data.drugGroup?.conceptGroup ?? []
    const seen = new Set<string>()
    const results: RxNormSuggestion[] = []

    // Prefer SCD (clinical drugs) and IN (ingredients) TTYs
    const preferred = ["SCD", "IN", "BN", "PIN"]
    const ordered = [
      ...groups.filter((g) => preferred.includes(g.tty ?? "")),
      ...groups.filter((g) => !preferred.includes(g.tty ?? "")),
    ]

    for (const group of ordered) {
      for (const c of group.conceptProperties ?? []) {
        if (!seen.has(c.rxcui) && results.length < 8) {
          seen.add(c.rxcui)
          results.push({ rxcui: c.rxcui, name: c.name, synonym: c.synonym || null })
        }
      }
    }

    return results
  } catch {
    return []
  }
}

// ─── Queries ──────────────────────────────────────────────────────────────────

export async function getMedications(): Promise<{
  active: MedRow[]
  inactive: MedRow[]
}> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { data } = await (supabase as any)
    .from("medications")
    .select(
      "id, name, rxnorm_code, generic_name, brand_name, dose_amount, dose_unit, frequency, route, timing, indication, prescribing_provider, started_date, stopped_date, status, notes"
    )
    .eq("user_id", user.id)
    .is("valid_until", null)
    .order("status")
    .order("name")

  const rows = (data ?? []) as MedRow[]
  return {
    active: rows.filter((r) => r.status === "active" || r.status === "paused"),
    inactive: rows.filter((r) => r.status === "discontinued"),
  }
}

// ─── Mutations ────────────────────────────────────────────────────────────────

export async function addMedication(
  _prev: { error?: string } | null,
  formData: FormData
): Promise<{ error?: string }> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const name = (formData.get("name") as string | null)?.trim()
  if (!name) return { error: "Medication name is required." }

  const doseAmountRaw = formData.get("dose_amount") as string | null
  const doseAmount = doseAmountRaw ? parseFloat(doseAmountRaw) : null

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { error } = await (supabase as any).from("medications").insert({
    user_id:              user.id,
    name,
    rxnorm_code:          formData.get("rxnorm_code") || null,
    generic_name:         formData.get("generic_name") || null,
    brand_name:           formData.get("brand_name") || null,
    dose_amount:          doseAmount && !isNaN(doseAmount) ? doseAmount : null,
    dose_unit:            formData.get("dose_unit") || null,
    frequency:            formData.get("frequency") || null,
    route:                formData.get("route") || null,
    timing:               formData.get("timing") || null,
    indication:           formData.get("indication") || null,
    prescribing_provider: formData.get("prescribing_provider") || null,
    started_date:         formData.get("started_date") || new Date().toISOString().split("T")[0],
    status:               "active",
    last_confirmed_at:    new Date().toISOString(),
    source:               "self_reported",
    notes:                formData.get("notes") || null,
  })

  if (error) return { error: (error as { message: string }).message }

  revalidatePath("/medications")
  redirect("/medications")
}

export async function updateMedication(
  id: string,
  _prev: { error?: string } | null,
  formData: FormData
): Promise<{ error?: string }> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const doseAmountRaw = formData.get("dose_amount") as string | null
  const doseAmount = doseAmountRaw ? parseFloat(doseAmountRaw) : null

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { error } = await (supabase as any)
    .from("medications")
    .update({
      dose_amount:          doseAmount && !isNaN(doseAmount) ? doseAmount : null,
      dose_unit:            formData.get("dose_unit") || null,
      frequency:            formData.get("frequency") || null,
      route:                formData.get("route") || null,
      timing:               formData.get("timing") || null,
      indication:           formData.get("indication") || null,
      prescribing_provider: formData.get("prescribing_provider") || null,
      notes:                formData.get("notes") || null,
      last_confirmed_at:    new Date().toISOString(),
    })
    .eq("id", id)
    .eq("user_id", user.id)

  if (error) return { error: (error as { message: string }).message }

  revalidatePath("/medications")
  redirect("/medications")
}

export async function discontinueMedication(id: string): Promise<void> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await (supabase as any)
    .from("medications")
    .update({
      status:       "discontinued",
      stopped_date: new Date().toISOString().split("T")[0],
      valid_until:  new Date().toISOString(),
    })
    .eq("id", id)
    .eq("user_id", user.id)

  revalidatePath("/medications")
}

export async function deleteMedication(id: string): Promise<void> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await (supabase as any)
    .from("medications")
    .delete()
    .eq("id", id)
    .eq("user_id", user.id)

  revalidatePath("/medications")
}
