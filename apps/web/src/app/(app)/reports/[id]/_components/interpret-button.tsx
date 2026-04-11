"use client"

import { useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import { requestInterpretation } from "../../actions"

export function InterpretButton({ reportId }: { reportId: string }) {
  const router = useRouter()
  const [, startTransition] = useTransition()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleClick() {
    setLoading(true)
    setError(null)
    const result = await requestInterpretation(reportId)
    setLoading(false)
    if (result.error) {
      setError(result.error)
    } else {
      startTransition(() => router.refresh())
    }
  }

  return (
    <div className="space-y-2">
      <button
        onClick={handleClick}
        disabled={loading}
        className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:from-blue-500 hover:to-indigo-500 disabled:opacity-60 transition-all"
      >
        {loading ? (
          <>
            <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Analysing with AI…
          </>
        ) : (
          <>
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
            Get AI interpretation
          </>
        )}
      </button>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
