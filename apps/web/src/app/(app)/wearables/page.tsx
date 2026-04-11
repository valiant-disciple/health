import { getWearableStatus } from "./actions"
import { AppleHealthUpload } from "./_components/apple-health-upload"
import { FitbitCard } from "./_components/fitbit-card"

export default async function WearablesPage() {
  const status = await getWearableStatus()

  const fitbit      = status["fitbit"]
  const appleHealth = status["apple_health"]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Connected devices</h1>
        <p className="mt-1 text-sm text-gray-500">
          Link your wearables and health apps to build a complete longitudinal health picture.
        </p>
      </div>

      {/* What gets synced */}
      <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-blue-500">What gets synced</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {[
            "Heart rate", "Resting HR", "HRV", "Steps", "Sleep",
            "SpO₂", "Weight", "BMI", "Body fat", "Calories",
          ].map((label) => (
            <span key={label} className="rounded-full bg-white px-2.5 py-1 text-xs text-gray-600 shadow-sm">
              {label}
            </span>
          ))}
        </div>
        <p className="mt-2 text-xs text-gray-500">
          All data is mapped to LOINC codes and added to your health timeline. Your AI health assistant can reason over it immediately.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <FitbitCard
          connected={fitbit?.connected ?? false}
          lastSyncedAt={fitbit?.last_synced_at ?? null}
        />
        <AppleHealthUpload />
      </div>

      {/* Coming soon */}
      <div className="grid gap-4 sm:grid-cols-2">
        {[
          { name: "Google Fit", color: "bg-green-50", text: "text-green-500" },
          { name: "Garmin Connect", color: "bg-orange-50", text: "text-orange-500" },
          { name: "Withings", color: "bg-purple-50", text: "text-purple-500" },
          { name: "Oura Ring", color: "bg-indigo-50", text: "text-indigo-500" },
        ].map((provider) => (
          <div key={provider.name} className="rounded-2xl border border-gray-100 bg-white p-6 opacity-60">
            <div className="flex items-center gap-3">
              <div className={`flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl ${provider.color}`}>
                <svg className={`h-5 w-5 ${provider.text}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <p className="font-semibold text-gray-900">{provider.name}</p>
                <p className="text-xs text-gray-400">Coming soon</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
