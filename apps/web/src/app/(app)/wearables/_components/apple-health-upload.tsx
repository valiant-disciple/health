"use client"

import { useActionState, useRef } from "react"
import { uploadAppleHealth } from "../actions"

export function AppleHealthUpload() {
  const [state, action, pending] = useActionState(uploadAppleHealth, null)
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <form action={action}>
      <div className="rounded-2xl border border-gray-100 bg-white p-6">
        <div className="flex items-start gap-4">
          <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-red-50">
            {/* Apple Health heart icon */}
            <svg className="h-6 w-6 text-red-500" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 21.593c-5.63-5.539-11-10.297-11-14.402 0-3.791 3.068-5.191 5.281-5.191 1.312 0 4.151.501 5.719 4.457 1.59-3.968 4.464-4.447 5.726-4.447 2.54 0 5.274 1.621 5.274 5.181 0 4.069-5.136 8.625-11 14.402z"/>
            </svg>
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-gray-900">Apple Health</h3>
            <p className="mt-0.5 text-sm text-gray-500">
              Upload your iPhone Health export to sync heart rate, steps, sleep, weight and more.
            </p>

            <div className="mt-3 rounded-xl border border-dashed border-gray-200 bg-gray-50 p-4 text-xs text-gray-500">
              <p className="font-medium text-gray-700">How to export from iPhone:</p>
              <ol className="mt-1 list-decimal pl-4 space-y-0.5">
                <li>Open the <strong>Health</strong> app on your iPhone</li>
                <li>Tap your profile picture → <strong>Export All Health Data</strong></li>
                <li>Share the <code className="rounded bg-gray-200 px-1">export.zip</code> file here</li>
              </ol>
            </div>

            <div className="mt-4">
              <input
                ref={inputRef}
                type="file"
                name="file"
                accept=".xml,.zip"
                className="hidden"
                id="apple-health-file"
              />
              <label
                htmlFor="apple-health-file"
                className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
              >
                <svg className="h-4 w-4 text-gray-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                Choose file
              </label>
            </div>

            {state?.error && (
              <p className="mt-3 text-xs text-red-600">{state.error}</p>
            )}
            {state?.success && (
              <p className="mt-3 text-xs text-green-700">{state.success}</p>
            )}

            <button
              type="submit"
              disabled={pending}
              className="mt-3 flex items-center gap-2 rounded-xl bg-red-500 px-5 py-2 text-sm font-semibold text-white hover:bg-red-400 disabled:opacity-60 transition-all"
            >
              {pending ? (
                <>
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Uploading…
                </>
              ) : "Import"}
            </button>
          </div>
        </div>
      </div>
    </form>
  )
}
