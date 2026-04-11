import Link from "next/link"
import { getMedications } from "./actions"
import { MedCard } from "./_components/med-card"

export default async function MedicationsPage() {
  const { active, inactive } = await getMedications()

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Medications</h1>
          <p className="mt-1 text-sm text-gray-500">
            {active.length === 0
              ? "No active medications"
              : `${active.length} active medication${active.length === 1 ? "" : "s"}`}
          </p>
        </div>
        <Link
          href="/medications/add"
          className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 transition-colors"
        >
          + Add medication
        </Link>
      </div>

      {/* Empty state */}
      {active.length === 0 && inactive.length === 0 && (
        <div className="rounded-2xl border-2 border-dashed border-gray-200 py-16 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50">
            <svg className="h-6 w-6 text-blue-500" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
            </svg>
          </div>
          <h3 className="mt-4 text-sm font-semibold text-gray-900">No medications yet</h3>
          <p className="mt-1 text-sm text-gray-500">
            Add your medications so the AI can check for interactions and flag relevant lab results.
          </p>
          <Link
            href="/medications/add"
            className="mt-4 inline-block rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 transition-colors"
          >
            Add first medication
          </Link>
        </div>
      )}

      {/* Active medications */}
      {active.length > 0 && (
        <section className="space-y-3">
          {active.map((med) => (
            <MedCard key={med.id} med={med} />
          ))}
        </section>
      )}

      {/* Discontinued */}
      {inactive.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
            Past medications
          </h2>
          {inactive.map((med) => (
            <MedCard key={med.id} med={med} showActions={false} />
          ))}
        </section>
      )}

      {/* AI context note */}
      {active.length > 0 && (
        <p className="text-center text-xs text-gray-400">
          Your medication list is used by the AI to check drug interactions and contextualise lab results.
        </p>
      )}
    </div>
  )
}
