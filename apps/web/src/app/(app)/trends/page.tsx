import Link from "next/link"
import { getTrendsData } from "./actions"
import { BiomarkerChart } from "./_components/biomarker-chart"
import { HealthTimeline } from "../dashboard/_components/timeline"

export default async function TrendsPage() {
  const { series, timeline } = await getTrendsData()

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Trends</h1>
        <p className="mt-1 text-sm text-gray-500">
          Biomarker history and your full health timeline
        </p>
      </div>

      {/* Biomarker charts */}
      <section className="space-y-4">
        <h2 className="text-base font-semibold text-gray-900">Biomarker trends</h2>

        {series.length === 0 ? (
          <div className="rounded-2xl border-2 border-dashed border-gray-100 py-16 text-center">
            <p className="text-sm text-gray-400">No biomarker data yet.</p>
            <Link
              href="/reports/upload"
              className="mt-3 inline-block rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-500 transition-colors"
            >
              Upload lab report →
            </Link>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {series.map((s) => (
              <BiomarkerChart key={s.code} series={s} />
            ))}
          </div>
        )}
      </section>

      {/* Full timeline */}
      <section className="space-y-4">
        <h2 className="text-base font-semibold text-gray-900">Full timeline</h2>
        <HealthTimeline events={timeline} showViewAll={false} />
      </section>
    </div>
  )
}
