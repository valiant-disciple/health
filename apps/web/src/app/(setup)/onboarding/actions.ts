"use server"

import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import { revalidatePath } from "next/cache"

export type Sex = "male" | "female" | "other" | "prefer_not_to_say"
export type ActivityLevel = "sedentary" | "light" | "moderate" | "active" | "very_active"
export type Severity = "mild" | "moderate" | "severe" | "in_remission"

export interface OnboardingData {
  display_name: string
  date_of_birth: string
  sex: Sex
  timezone: string
  height_cm: number | null
  weight_kg: number | null
  activity_level: ActivityLevel
  health_goals: string[]
  dietary_restrictions: string[]
  conditions: Array<{ name: string; severity: Severity }>
}

export async function saveOnboarding(
  data: OnboardingData
): Promise<{ error: string } | null> {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = supabase as any

  const { error: profileError } = await db.from("user_profile").upsert({
    id: user.id,
    display_name: data.display_name,
    date_of_birth: data.date_of_birth || null,
    sex: data.sex,
    timezone: data.timezone,
    height_cm: data.height_cm,
    weight_kg: data.weight_kg,
    activity_level: data.activity_level,
    health_goals: data.health_goals,
    dietary_restrictions: data.dietary_restrictions,
    onboarding_complete: true,
  })

  if (profileError) return { error: (profileError as { message: string }).message }

  if (data.conditions.length > 0) {
    const { error: condError } = await db.from("health_conditions").insert(
      data.conditions.map((c) => ({
        user_id: user.id,
        name: c.name,
        severity: c.severity,
        source: "self_reported",
      }))
    )
    if (condError) return { error: (condError as { message: string }).message }
  }

  revalidatePath("/dashboard")
  redirect("/dashboard")
}
