"use server"

import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import { revalidatePath } from "next/cache"

const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://localhost:8000"

export interface WearableStatus {
  provider: string
  connected: boolean
  last_synced_at: string | null
}

export async function getWearableStatus(): Promise<Record<string, WearableStatus>> {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const res = await fetch(`${AI_SERVICE_URL}/wearables/status`, {
    headers: { "X-User-Id": user.id },
    next: { revalidate: 30 },
  })
  if (!res.ok) return {}
  return res.json()
}

export async function connectFitbit(): Promise<{ auth_url?: string; error?: string }> {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const res = await fetch(`${AI_SERVICE_URL}/wearables/fitbit/connect`, {
    method: "GET",
    headers: { "X-User-Id": user.id },
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => "")
    return { error: txt || "Failed to initiate Fitbit connection" }
  }
  const data = await res.json() as { auth_url: string }
  return { auth_url: data.auth_url }
}

export async function syncFitbit(): Promise<{ error?: string }> {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const res = await fetch(`${AI_SERVICE_URL}/wearables/fitbit/sync`, {
    method: "POST",
    headers: { "X-User-Id": user.id },
  })
  if (!res.ok) return { error: "Sync failed" }
  revalidatePath("/wearables")
  revalidatePath("/trends")
  return {}
}

export async function disconnectWearable(provider: string): Promise<{ error?: string }> {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const res = await fetch(`${AI_SERVICE_URL}/wearables/${provider}`, {
    method: "DELETE",
    headers: { "X-User-Id": user.id },
  })
  if (!res.ok) return { error: "Disconnect failed" }
  revalidatePath("/wearables")
  return {}
}

export async function uploadAppleHealth(
  _prevState: { error?: string; success?: string } | null,
  formData: FormData,
): Promise<{ error?: string; success?: string }> {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const file = formData.get("file") as File | null
  if (!file || !file.name) return { error: "No file selected." }

  const ext = file.name.split(".").pop()?.toLowerCase()
  if (ext !== "xml" && ext !== "zip") return { error: "Please upload export.xml or export.zip from the iPhone Health app." }

  if (file.size > 200 * 1024 * 1024) return { error: "File must be under 200 MB." }

  const fd = new FormData()
  fd.append("file", file)

  const res = await fetch(`${AI_SERVICE_URL}/wearables/apple-health/upload`, {
    method: "POST",
    headers: { "X-User-Id": user.id },
    body: fd,
  })

  if (!res.ok) {
    const txt = await res.text().catch(() => "")
    return { error: txt || "Upload failed" }
  }

  revalidatePath("/wearables")
  revalidatePath("/trends")
  return { success: "Import started — your data will appear in Trends within a minute." }
}
