"use client"

import { useState, useTransition } from "react"
import { connectFitbit, syncFitbit, disconnectWearable } from "../actions"
import { useRouter } from "next/navigation"

export function FitbitCard({
  connected,
  lastSyncedAt,
}: {
  connected: boolean
  lastSyncedAt: string | null
}) {
  const router = useRouter()
  const [, startTransition] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)

  async function handleConnect() {
    setError(null)
    const result = await connectFitbit()
    if (result.error) {
      setError(result.error)
    } else if (result.auth_url) {
      window.location.href = result.auth_url
    }
  }

  async function handleSync() {
    setSyncing(true)
    setError(null)
    const result = await syncFitbit()
    setSyncing(false)
    if (result.error) setError(result.error)
    else startTransition(() => router.refresh())
  }

  async function handleDisconnect() {
    setDisconnecting(true)
    await disconnectWearable("fitbit")
    setDisconnecting(false)
    startTransition(() => router.refresh())
  }

  const lastSync = lastSyncedAt
    ? new Date(lastSyncedAt).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : null

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6">
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-blue-50">
          {/* Fitbit icon */}
          <svg className="h-6 w-6 text-blue-500" viewBox="0 0 24 24" fill="currentColor">
            <circle cx="12" cy="4" r="2" />
            <circle cx="12" cy="12" r="2.5" />
            <circle cx="12" cy="20" r="2" />
            <circle cx="4" cy="8" r="1.5" />
            <circle cx="20" cy="8" r="1.5" />
            <circle cx="4" cy="16" r="1.5" />
            <circle cx="20" cy="16" r="1.5" />
          </svg>
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-gray-900">Fitbit</h3>
            {connected ? (
              <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                Connected
              </span>
            ) : (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
                Not connected
              </span>
            )}
          </div>

          <p className="mt-0.5 text-sm text-gray-500">
            Sync heart rate, steps, sleep, SpO2, and body metrics automatically.
          </p>

          {connected && lastSync && (
            <p className="mt-1 text-xs text-gray-400">Last synced: {lastSync}</p>
          )}

          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

          <div className="mt-4 flex flex-wrap gap-2">
            {connected ? (
              <>
                <button
                  onClick={handleSync}
                  disabled={syncing}
                  className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-60 transition-all"
                >
                  {syncing ? (
                    <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                  ) : (
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                    </svg>
                  )}
                  {syncing ? "Syncing…" : "Sync now"}
                </button>
                <button
                  onClick={handleDisconnect}
                  disabled={disconnecting}
                  className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-60 transition-all"
                >
                  Disconnect
                </button>
              </>
            ) : (
              <button
                onClick={handleConnect}
                className="flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-500 transition-all"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101"/>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M14.828 14.828a4 4 0 015.656 0l4 4a4 4 0 01-5.656 5.656l-1.102-1.101"/>
                </svg>
                Connect Fitbit
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
