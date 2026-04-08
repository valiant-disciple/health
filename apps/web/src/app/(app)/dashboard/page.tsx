import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"

export default async function DashboardPage() {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) redirect("/login")

  // Check onboarding completion
  const { data: profile } = await supabase
    .from("user_profile")
    .select("onboarding_complete, display_name")
    .eq("id", user.id)
    .single()

  if (!profile?.onboarding_complete) {
    redirect("/onboarding")
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">
          Good morning{profile?.display_name ? `, ${profile.display_name}` : ""}
        </h1>
        <p className="mt-1 text-sm text-gray-500">Here is your health overview</p>
      </div>

      {/* Placeholder sections — filled in on Day 5 */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard title="Lab Reports" value="—" subtitle="Upload your first report" href="/reports/upload" />
        <StatCard title="Medications" value="—" subtitle="Add your medications" href="/medications" />
        <StatCard title="Recent Activity" value="—" subtitle="No activity yet" href="/trends" />
      </div>
    </div>
  )
}

function StatCard({
  title,
  value,
  subtitle,
  href,
}: {
  title: string
  value: string
  subtitle: string
  href: string
}) {
  return (
    <a
      href={href}
      className="block rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:shadow-md"
    >
      <p className="text-sm font-medium text-gray-500">{title}</p>
      <p className="mt-1 text-3xl font-bold text-gray-900">{value}</p>
      <p className="mt-1 text-xs text-gray-400">{subtitle}</p>
    </a>
  )
}
