import Link from "next/link"
import { MedForm } from "../_components/med-form"
import { addMedication } from "../actions"

export default function AddMedicationPage() {
  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-6">
        <Link
          href="/medications"
          className="text-xs font-medium text-gray-400 hover:text-gray-600 transition-colors"
        >
          ← Back to medications
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Add medication</h1>
        <p className="mt-1 text-sm text-gray-500">
          Search by name — we&apos;ll look it up in RxNorm for standardised coding.
        </p>
      </div>

      <div className="rounded-3xl border border-gray-100 bg-white p-8 shadow-xl shadow-gray-100/60">
        <MedForm action={addMedication} submitLabel="Add medication" />
      </div>
    </div>
  )
}
