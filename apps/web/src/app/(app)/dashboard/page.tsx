import { redirect } from "next/navigation"
import { createClient } from "@/lib/supabase/server"
import { getDashboardData } from "./actions"
import { Greeting } from "./_components/greeting"
import { StatCard } from "./_components/stat-card"
import { HealthTimeline } from "./_components/timeline"

// Icons (inline SVG to avoid extra deps)
function IconFlask() {
  return (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15M14.25 3.104c.251.023.501.05.75.082M19.8 15a2.25 2.25 0 010 4.5 2.25 2.25 0 010-4.5zm-15.6 0a2.25 2.25 0 010 4.5 2.25 2.25 0 010-4.5zm4.134-1.499l1.204-1.204a.75.75 0 011.06 0l1.204 1.204" />
    </svg>
  )
}
function IconPill() {
  return (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15M14.25 3.104c.251.023.501.05.75.082M5 14.5h14M5 14.5a2.25 2.25 0 000 4.5m14-4.5a2.25 2.25 0 010 4.5" />
    </svg>
  )
}
function IconAlert() {
  return (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  )
}
function IconChat() {
  return (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
    </svg>
  )
}

export default async function DashboardPage() {
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  const { stats, timeline, profile } = await getDashboardData()

  if (!profile.onboarding_complete) redirect("/onboarding")

  const hasData = stats.reportsTotal > 0 || stats.activeMeds > 0

  return (
    <div className="space-y-8">
      {/* Greeting */}
      <Greeting name={profile.display_name} />

      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Lab Reports"
          value={stats.reportsTotal}
          subtitle={
            stats.reportsPending > 0
              ? `${stats.reportsPending} processing`
              : stats.reportsTotal === 0
                ? "Upload your first report"
                : "All processed"
          }
          href="/reports"
          accent="blue"
          badge={
            stats.reportsPending > 0
              ? { label: `${stats.reportsPending} pending`, variant: "pulse" }
              : undefined
          }
          icon={<IconFlask />}
        />
        <StatCard
          title="Active Medications"
          value={stats.activeMeds}
          subtitle={
            stats.activeMeds === 0
              ? "Add your medications"
              : `${stats.activeMeds} medication${stats.activeMeds === 1 ? "" : "s"} tracked`
          }
          href="/medications"
          accent="green"
          icon={<IconPill />}
        />
        <StatCard
          title="Abnormal Results"
          value={stats.abnormalResults + stats.criticalResults}
          subtitle={
            stats.criticalResults > 0
              ? `${stats.criticalResults} critical · discuss with doctor`
              : stats.abnormalResults > 0
                ? "Review in last 90 days"
                : "All in normal range"
          }
          href="/reports"
          accent={stats.criticalResults > 0 ? "red" : stats.abnormalResults > 0 ? "orange" : "green"}
          badge={
            stats.criticalResults > 0
              ? { label: "Critical", variant: "pulse" }
              : undefined
          }
          icon={<IconAlert />}
        />
        <StatCard
          title="Ask health AI"
          value="Chat"
          subtitle="Ask about your results, meds, or trends"
          href="/chat"
          accent="purple"
          icon={<IconChat />}
        />
      </div>

      {/* Main content grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Timeline — takes 2 cols */}
        <div className="lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900">Recent activity</h2>
            {timeline.length > 0 && (
              <a href="/trends" className="text-xs font-medium text-blue-600 hover:underline">
                View all →
              </a>
            )}
          </div>
          <HealthTimeline events={timeline} showViewAll={timeline.length >= 10} />
        </div>

        {/* Quick actions sidebar */}
        <div className="space-y-4">
          <h2 className="text-base font-semibold text-gray-900">Quick actions</h2>

          {!hasData && (
            <div className="rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50 to-indigo-50 p-5">
              <p className="text-sm font-semibold text-blue-800">Get started</p>
              <p className="mt-1 text-xs text-blue-600">
                Upload your first lab report to unlock personalised insights.
              </p>
              <a
                href="/reports/upload"
                className="mt-3 inline-block rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-500 transition-colors"
              >
                Upload lab report →
              </a>
            </div>
          )}

          <div className="space-y-2">
            {[
              { label: "Upload lab report", href: "/reports/upload", emoji: "📋" },
              { label: "Add medication",    href: "/medications/add", emoji: "💊" },
              { label: "Ask health AI",     href: "/chat",            emoji: "🤖" },
              { label: "View trends",       href: "/trends",          emoji: "📈" },
            ].map(({ label, href, emoji }) => (
              <a
                key={href}
                href={href}
                className="flex items-center gap-3 rounded-xl border border-gray-100 bg-white px-4 py-3 text-sm font-medium text-gray-700 shadow-sm transition hover:shadow-md hover:text-blue-700"
              >
                <span className="text-base">{emoji}</span>
                {label}
                <span className="ml-auto text-gray-300">→</span>
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
