"use client"

import { useState, useTransition } from "react"
import Link from "next/link"
import { cn } from "@/lib/utils"
import { discontinueMedication, deleteMedication } from "../actions"
import type { MedRow } from "../actions"

const STATUS_BADGE: Record<string, string> = {
  active:        "bg-green-100 text-green-700",
  paused:        "bg-yellow-100 text-yellow-700",
  discontinued:  "bg-gray-100 text-gray-500",
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" })
}

export function MedCard({ med, showActions = true }: { med: MedRow; showActions?: boolean }) {
  const [pending, startTransition] = useTransition()
  const [confirming, setConfirming] = useState<"discontinue" | "delete" | null>(null)
  const isActive = med.status === "active" || med.status === "paused"

  function doDiscontinue() {
    startTransition(async () => {
      await discontinueMedication(med.id)
      setConfirming(null)
    })
  }

  function doDelete() {
    startTransition(async () => {
      await deleteMedication(med.id)
      setConfirming(null)
    })
  }

  return (
    <div
      className={cn(
        "rounded-2xl border bg-white p-5 shadow-sm transition hover:shadow-md",
        isActive ? "border-gray-100" : "border-gray-100 opacity-70"
      )}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-semibold text-gray-900 truncate">{med.name}</h3>
            <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", STATUS_BADGE[med.status] ?? STATUS_BADGE["active"])}>
              {med.status.charAt(0).toUpperCase() + med.status.slice(1)}
            </span>
          </div>
          {med.generic_name && med.generic_name !== med.name && (
            <p className="mt-0.5 text-xs text-gray-400">{med.generic_name}</p>
          )}
        </div>
        {med.rxnorm_code && (
          <span className="flex-shrink-0 rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-xs text-blue-500">
            RxNorm
          </span>
        )}
      </div>

      {/* Details grid */}
      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3">
        {med.dose_amount != null && (
          <Detail label="Dose" value={`${med.dose_amount}${med.dose_unit ? ` ${med.dose_unit}` : ""}`} />
        )}
        {med.frequency && <Detail label="Frequency" value={med.frequency} />}
        {med.timing && <Detail label="Timing" value={med.timing} />}
        {med.route && <Detail label="Route" value={med.route} />}
        {med.indication && <Detail label="For" value={med.indication} />}
        {med.started_date && <Detail label="Since" value={fmtDate(med.started_date)} />}
        {med.prescribing_provider && (
          <Detail label="Prescribed by" value={med.prescribing_provider} />
        )}
      </div>

      {med.notes && (
        <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">{med.notes}</p>
      )}

      {/* Actions */}
      {showActions && isActive && (
        <div className="mt-4 flex items-center gap-2 border-t border-gray-50 pt-3">
          <Link
            href={`/medications/${med.id}/edit`}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            Edit
          </Link>

          {confirming === "discontinue" ? (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-500">Mark as discontinued?</span>
              <button
                onClick={doDiscontinue}
                disabled={pending}
                className="rounded-lg bg-orange-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-orange-400 disabled:opacity-50"
              >
                {pending ? "…" : "Confirm"}
              </button>
              <button
                onClick={() => setConfirming(null)}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirming("discontinue")}
              className="rounded-lg border border-orange-200 px-3 py-1.5 text-xs font-medium text-orange-600 hover:bg-orange-50 transition-colors"
            >
              Discontinue
            </button>
          )}

          {confirming === "delete" ? (
            <div className="flex items-center gap-1.5 ml-auto">
              <span className="text-xs text-gray-500">Delete permanently?</span>
              <button
                onClick={doDelete}
                disabled={pending}
                className="rounded-lg bg-red-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-400 disabled:opacity-50"
              >
                {pending ? "…" : "Delete"}
              </button>
              <button
                onClick={() => setConfirming(null)}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirming("delete")}
              className="ml-auto text-xs text-gray-400 hover:text-red-500 transition-colors"
            >
              Remove
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-gray-400">{label}</p>
      <p className="text-sm font-medium text-gray-800">{value}</p>
    </div>
  )
}
