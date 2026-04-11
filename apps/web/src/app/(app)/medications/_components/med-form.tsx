"use client"

import { useActionState, useCallback, useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { searchRxNorm, type RxNormSuggestion } from "../actions"

// ─── Constants ────────────────────────────────────────────────────────────────

const DOSE_UNITS = ["mg", "mcg", "g", "mL", "IU", "units", "tablet", "capsule", "drop", "patch"]
const FREQUENCIES = [
  "Once daily",
  "Twice daily",
  "Three times daily",
  "Four times daily",
  "Every other day",
  "Weekly",
  "As needed (PRN)",
]
const ROUTES = ["Oral", "Topical", "Inhaled", "Subcutaneous", "Intravenous", "Sublingual", "Nasal", "Ophthalmic"]
const TIMINGS = ["Morning", "Afternoon", "Evening", "Bedtime", "With food", "Without food", "Before bed"]

// ─── Props ────────────────────────────────────────────────────────────────────

type ActionFn = (
  prev: { error?: string } | null,
  formData: FormData
) => Promise<{ error?: string }>

interface Props {
  action: ActionFn
  defaultValues?: {
    name?: string | null
    rxnorm_code?: string | null
    generic_name?: string | null
    brand_name?: string | null
    dose_amount?: number | null
    dose_unit?: string | null
    frequency?: string | null
    route?: string | null
    timing?: string | null
    indication?: string | null
    prescribing_provider?: string | null
    started_date?: string
    notes?: string | null
  }
  submitLabel?: string
  isEdit?: boolean
}

// ─── RxNorm search box ────────────────────────────────────────────────────────

function RxSearch({
  defaultName,
  defaultRxcui,
  defaultGeneric,
  defaultBrand,
}: {
  defaultName?: string | undefined
  defaultRxcui?: string | undefined
  defaultGeneric?: string | undefined
  defaultBrand?: string | undefined
}) {
  const [query, setQuery] = useState(defaultName ?? "")
  const [suggestions, setSuggestions] = useState<RxNormSuggestion[]>([])
  const [open, setOpen] = useState(false)
  const [rxcui, setRxcui] = useState(defaultRxcui ?? "")
  const [generic, setGeneric] = useState(defaultGeneric ?? "")
  const [brand, setBrand] = useState(defaultBrand ?? "")
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const search = useCallback(async (q: string) => {
    if (q.length < 2) { setSuggestions([]); return }
    const res = await searchRxNorm(q)
    setSuggestions(res)
    setOpen(res.length > 0)
  }, [])

  function handleInput(value: string) {
    setQuery(value)
    setRxcui("")
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => void search(value), 350)
  }

  function pick(s: RxNormSuggestion) {
    setQuery(s.name)
    setRxcui(s.rxcui)
    setGeneric(s.synonym ?? "")
    setSuggestions([])
    setOpen(false)
  }

  return (
    <div className="space-y-4">
      {/* Hidden fields */}
      <input type="hidden" name="rxnorm_code" value={rxcui} />
      <input type="hidden" name="generic_name" value={generic} />
      <input type="hidden" name="brand_name"   value={brand} />

      {/* Name input with autocomplete */}
      <div className="space-y-1.5">
        <label className="text-sm font-medium text-gray-700">
          Medication name <span className="text-red-500">*</span>
        </label>
        <div className="relative">
          <input
            name="name"
            type="text"
            required
            autoComplete="off"
            value={query}
            onChange={(e) => handleInput(e.target.value)}
            onBlur={() => setTimeout(() => setOpen(false), 200)}
            onFocus={() => suggestions.length > 0 && setOpen(true)}
            placeholder="Search by name e.g. Metformin, Lisinopril…"
            className="w-full rounded-xl border border-gray-200 px-4 py-3 text-sm text-gray-900 placeholder-gray-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />

          {/* Suggestions dropdown */}
          {open && (
            <div className="absolute z-20 mt-1 w-full rounded-xl border border-gray-100 bg-white shadow-lg">
              {suggestions.map((s) => (
                <button
                  key={s.rxcui}
                  type="button"
                  onMouseDown={() => pick(s)}
                  className="flex w-full flex-col px-4 py-2.5 text-left transition-colors hover:bg-blue-50 first:rounded-t-xl last:rounded-b-xl"
                >
                  <span className="text-sm font-medium text-gray-900">{s.name}</span>
                  {s.synonym && s.synonym !== s.name && (
                    <span className="text-xs text-gray-400">{s.synonym}</span>
                  )}
                  <span className="text-xs text-gray-300">RxCUI {s.rxcui}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {rxcui && (
          <p className="flex items-center gap-1 text-xs text-green-600">
            <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            RxNorm verified · RxCUI {rxcui}
          </p>
        )}
      </div>

      {/* Brand name — manually override if needed */}
      <FieldRow label="Brand name (optional)">
        <input
          type="text"
          value={brand}
          onChange={(e) => setBrand(e.target.value)}
          placeholder="e.g. Glucophage"
          className={inputClass}
        />
      </FieldRow>
    </div>
  )
}

// ─── Small helpers ────────────────────────────────────────────────────────────

const inputClass =
  "w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-300 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"

const selectClass =
  "w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-900 bg-white focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium text-gray-700">{label}</label>
      {children}
    </div>
  )
}

// ─── Main form ────────────────────────────────────────────────────────────────

export function MedForm({ action, defaultValues: dv = {}, submitLabel = "Save medication", isEdit = false }: Props) {
  const [state, formAction, pending] = useActionState(action, null)

  return (
    <form action={formAction} className="space-y-5">
      {state?.error && (
        <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{state.error}</div>
      )}

      {/* RxNorm search — only shown for new medications */}
      {!isEdit ? (
        <RxSearch
          defaultName={dv.name ?? undefined}
          defaultRxcui={dv.rxnorm_code ?? undefined}
          defaultGeneric={dv.generic_name ?? undefined}
          defaultBrand={dv.brand_name ?? undefined}
        />
      ) : (
        <>
          <input type="hidden" name="rxnorm_code" value={dv.rxnorm_code ?? ""} />
          <input type="hidden" name="generic_name" value={dv.generic_name ?? ""} />
          <input type="hidden" name="brand_name"   value={dv.brand_name ?? ""} />
          <input type="hidden" name="name"         value={dv.name ?? ""} />
          <div className="rounded-xl bg-gray-50 px-4 py-3">
            <p className="text-sm font-semibold text-gray-900">{dv.name}</p>
            {dv.rxnorm_code && (
              <p className="text-xs text-gray-400">RxCUI {dv.rxnorm_code}</p>
            )}
          </div>
        </>
      )}

      {/* Dose */}
      <div className="grid grid-cols-2 gap-3">
        <FieldRow label="Dose amount">
          <input
            type="number"
            name="dose_amount"
            step="any"
            min="0"
            defaultValue={dv.dose_amount ?? ""}
            placeholder="e.g. 500"
            className={inputClass}
          />
        </FieldRow>
        <FieldRow label="Unit">
          <select name="dose_unit" defaultValue={dv.dose_unit ?? ""} className={selectClass}>
            <option value="">Select…</option>
            {DOSE_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </FieldRow>
      </div>

      {/* Frequency + timing */}
      <div className="grid grid-cols-2 gap-3">
        <FieldRow label="Frequency">
          <select name="frequency" defaultValue={dv.frequency ?? ""} className={selectClass}>
            <option value="">Select…</option>
            {FREQUENCIES.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </FieldRow>
        <FieldRow label="Timing">
          <select name="timing" defaultValue={dv.timing ?? ""} className={selectClass}>
            <option value="">Select…</option>
            {TIMINGS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </FieldRow>
      </div>

      {/* Route */}
      <FieldRow label="Route">
        <select name="route" defaultValue={dv.route ?? ""} className={selectClass}>
          <option value="">Select…</option>
          {ROUTES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </FieldRow>

      {/* Start date */}
      {!isEdit && (
        <FieldRow label="Date started">
          <input
            type="date"
            name="started_date"
            defaultValue={dv.started_date ?? new Date().toISOString().split("T")[0]}
            max={new Date().toISOString().split("T")[0]}
            className={inputClass}
          />
        </FieldRow>
      )}

      {/* Indication */}
      <FieldRow label="What it's for (indication)">
        <input
          type="text"
          name="indication"
          defaultValue={dv.indication ?? ""}
          placeholder="e.g. Type 2 diabetes, hypertension…"
          className={inputClass}
        />
      </FieldRow>

      {/* Prescribing provider */}
      <FieldRow label="Prescribing doctor (optional)">
        <input
          type="text"
          name="prescribing_provider"
          defaultValue={dv.prescribing_provider ?? ""}
          placeholder="e.g. Dr. Smith"
          className={inputClass}
        />
      </FieldRow>

      {/* Notes */}
      <FieldRow label="Notes (optional)">
        <textarea
          name="notes"
          rows={2}
          defaultValue={dv.notes ?? ""}
          placeholder="Any reminders, side effects, or instructions…"
          className={cn(inputClass, "resize-none")}
        />
      </FieldRow>

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-xl bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-40 transition-all"
      >
        {pending ? "Saving…" : submitLabel}
      </button>
    </form>
  )
}
