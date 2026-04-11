import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import { OnboardingWizard } from "./_components/wizard"

export default async function OnboardingPage() {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) redirect("/login")

  const { data: profile } = (await supabase
    .from("user_profile")
    .select("onboarding_complete")
    .eq("id", user.id)
    .single()) as { data: { onboarding_complete: boolean } | null }

  if (profile?.onboarding_complete) redirect("/dashboard")

  return <OnboardingWizard />
}
