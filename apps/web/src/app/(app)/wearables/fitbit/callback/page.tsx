"use client"

import { useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import Link from "next/link"

const AI_SERVICE_URL = process.env.NEXT_PUBLIC_AI_SERVICE_URL ?? "http://localhost:8000"

export default function FitbitCallbackPage() {
  const router = useRouter()
  const params = useSearchParams()
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading")
  const [errorMsg, setErrorMsg] = useState("")

  useEffect(() => {
    const code  = params.get("code")
    const state = params.get("state")
    const error = params.get("error")

    if (error) {
      setStatus("error")
      setErrorMsg(error === "access_denied" ? "You declined the Fitbit connection." : `Fitbit error: ${error}`)
      return
    }

    if (!code || !state) {
      setStatus("error")
      setErrorMsg("Missing OAuth parameters.")
      return
    }

    // user_id is embedded in state as "user_id:nonce"
    const userId = state.split(":")[0]
    if (!userId) {
      setStatus("error")
      setErrorMsg("Invalid state parameter.")
      return
    }

    fetch(`${AI_SERVICE_URL}/wearables/fitbit/callback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-User-Id": userId },
      body: JSON.stringify({ code, state }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const txt = await res.text().catch(() => "")
          throw new Error(txt || `HTTP ${res.status}`)
        }
        setStatus("success")
        setTimeout(() => router.push("/wearables"), 2000)
      })
      .catch((e: Error) => {
        setStatus("error")
        setErrorMsg(e.message)
      })
  }, [params, router])

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      {status === "loading" && (
        <>
          <svg className="h-10 w-10 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
          <p className="text-sm text-gray-600">Connecting your Fitbit account…</p>
        </>
      )}
      {status === "success" && (
        <>
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
            <svg className="h-6 w-6 text-green-600" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
          </div>
          <p className="text-sm font-semibold text-gray-900">Fitbit connected!</p>
          <p className="text-xs text-gray-500">Syncing your data now. Redirecting…</p>
        </>
      )}
      {status === "error" && (
        <>
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
            <svg className="h-6 w-6 text-red-600" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <p className="text-sm font-semibold text-gray-900">Connection failed</p>
          <p className="text-xs text-gray-500">{errorMsg}</p>
          <Link href="/wearables" className="mt-2 text-sm text-blue-600 underline">
            Back to wearables
          </Link>
        </>
      )}
    </div>
  )
}
