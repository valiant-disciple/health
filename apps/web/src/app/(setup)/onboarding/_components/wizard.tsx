"use client"

import { useState, useCallback } from "react"
import { cn } from "@/lib/utils"
import { saveOnboarding } from "../actions"
import type { Sex, ActivityLevel, Severity, OnboardingData } from "../actions"

// ─── Constants ────────────────────────────────────────────────────────────────

const ACTIVITY_LEVELS: {
  value: ActivityLevel
  label: string
  desc: string
  emoji: string
}[] = [
  { value: "sedentary", label: "Sedentary", desc: "Little to no exercise", emoji: "🪑" },
  { value: "light", label: "Light", desc: "1–3 days/week", emoji: "🚶" },
  { value: "moderate", label: "Moderate", desc: "3–5 days/week", emoji: "🏃" },
  { value: "active", label: "Active", desc: "6–7 days/week", emoji: "💪" },
  { value: "very_active", label: "Very active", desc: "Athlete / physical job", emoji: "🏋️" },
]

const HEALTH_GOALS = [
  "Understand my lab results",
  "Manage a chronic condition",
  "Optimise nutrition",
  "Track medications",
  "Improve fitness",
  "Monitor heart health",
  "Manage weight",
  "Better sleep",
  "Reduce stress",
  "Preventive care",
]

const DIETARY_RESTRICTIONS = [
  "Vegetarian",
  "Vegan",
  "Gluten-free",
  "Dairy-free",
  "Halal",
  "Kosher",
  "Low FODMAP",
  "Nut allergy",
  "Shellfish allergy",
  "Keto",
  "Low sodium",
  "Diabetic diet",
]

const SEVERITY_STYLES: Record<Severity, { badge: string; ring: string }> = {
  mild: {
    badge: "bg-yellow-100 text-yellow-800 border-yellow-200",
    ring: "border-yellow-400 bg-yellow-100 text-yellow-800",
  },
  moderate: {
    badge: "bg-orange-100 text-orange-800 border-orange-200",
    ring: "border-orange-400 bg-orange-100 text-orange-800",
  },
  severe: {
    badge: "bg-red-100 text-red-800 border-red-200",
    ring: "border-red-400 bg-red-100 text-red-800",
  },
  in_remission: {
    badge: "bg-green-100 text-green-800 border-green-200",
    ring: "border-green-400 bg-green-100 text-green-800",
  },
}

const SEVERITY_LABELS: Record<Severity, string> = {
  mild: "Mild",
  moderate: "Moderate",
  severe: "Severe",
  in_remission: "In remission",
}

const TOTAL_STEPS = 5

// ─── Types ────────────────────────────────────────────────────────────────────

interface FormState {
  display_name: string
  date_of_birth: string
  sex: Sex | ""
  timezone: string
  height_unit: "cm" | "ft"
  height_cm: string
  height_ft: string
  height_in: string
  weight_unit: "kg" | "lbs"
  weight_display: string
  activity_level: ActivityLevel | ""
  health_goals: string[]
  dietary_restrictions: string[]
  conditions: Array<{ name: string; severity: Severity }>
  condition_input: string
  condition_severity: Severity
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function ftInToCm(ft: string, inches: string): number {
  return (parseFloat(ft) || 0) * 30.48 + (parseFloat(inches) || 0) * 2.54
}

function lbsToKg(lbs: string): number {
  return (parseFloat(lbs) || 0) * 0.453592
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function UnitToggle({
  options,
  value,
  onChange,
}: {
  options: readonly [string, string]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="flex rounded-lg border border-gray-200 p-0.5 text-xs">
      {options.map((u) => (
        <button
          key={u}
          type="button"
          onClick={() => onChange(u)}
          className={cn(
            "rounded-md px-3 py-1 font-medium transition-all",
            value === u ? "bg-blue-600 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
          )}
        >
          {u}
        </button>
      ))}
    </div>
  )
}

function FieldInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "w-full rounded-xl border border-gray-200 px-4 py-3 text-base text-gray-900 placeholder-gray-300",
        "focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100 transition-shadow",
        props.className
      )}
    />
  )
}

function Chip({
  label,
  active,
  color = "blue",
  onClick,
}: {
  label: string
  active: boolean
  color?: "blue" | "emerald"
  onClick: () => void
}) {
  const activeClass =
    color === "blue"
      ? "border-blue-500 bg-blue-600 text-white"
      : "border-emerald-500 bg-emerald-600 text-white"
  const inactiveClass =
    color === "blue"
      ? "border-gray-200 text-gray-600 hover:border-blue-200 hover:bg-blue-50"
      : "border-gray-200 text-gray-600 hover:border-emerald-200 hover:bg-emerald-50"

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border-2 px-4 py-2 text-sm font-medium transition-all",
        active ? activeClass : inactiveClass
      )}
    >
      {label}
    </button>
  )
}

// ─── Wizard ───────────────────────────────────────────────────────────────────

export function OnboardingWizard() {
  const [step, setStep] = useState(0)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [form, setForm] = useState<FormState>({
    display_name: "",
    date_of_birth: "",
    sex: "",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    height_unit: "cm",
    height_cm: "",
    height_ft: "",
    height_in: "",
    weight_unit: "kg",
    weight_display: "",
    activity_level: "",
    health_goals: [],
    dietary_restrictions: [],
    conditions: [],
    condition_input: "",
    condition_severity: "mild",
  })

  const set = useCallback(
    <K extends keyof FormState>(key: K, value: FormState[K]) =>
      setForm((prev) => ({ ...prev, [key]: value })),
    []
  )

  function toggleArray(key: "health_goals" | "dietary_restrictions", value: string) {
    setForm((prev) => ({
      ...prev,
      [key]: prev[key].includes(value)
        ? prev[key].filter((x) => x !== value)
        : [...prev[key], value],
    }))
  }

  function addCondition() {
    const name = form.condition_input.trim()
    if (!name) return
    setForm((prev) => ({
      ...prev,
      conditions: [...prev.conditions, { name, severity: prev.condition_severity }],
      condition_input: "",
    }))
  }

  function removeCondition(i: number) {
    setForm((prev) => ({ ...prev, conditions: prev.conditions.filter((_, idx) => idx !== i) }))
  }

  function canProceed(): boolean {
    if (step === 0) return form.display_name.trim().length > 0
    if (step === 1) return form.sex !== ""
    return true
  }

  async function handleSubmit() {
    setSaving(true)
    setError(null)

    let height_cm: number | null = null
    let weight_kg: number | null = null

    if (form.height_unit === "cm" && form.height_cm) {
      const v = parseFloat(form.height_cm)
      if (!isNaN(v)) height_cm = v
    } else if (form.height_unit === "ft" && (form.height_ft || form.height_in)) {
      const v = ftInToCm(form.height_ft, form.height_in)
      if (!isNaN(v) && v > 0) height_cm = v
    }

    if (form.weight_display) {
      const v =
        form.weight_unit === "kg" ? parseFloat(form.weight_display) : lbsToKg(form.weight_display)
      if (!isNaN(v)) weight_kg = v
    }

    const data: OnboardingData = {
      display_name: form.display_name.trim(),
      date_of_birth: form.date_of_birth,
      sex: (form.sex || "prefer_not_to_say") as Sex,
      timezone: form.timezone,
      height_cm,
      weight_kg,
      activity_level: (form.activity_level || "sedentary") as ActivityLevel,
      health_goals: form.health_goals,
      dietary_restrictions: form.dietary_restrictions,
      conditions: form.conditions,
    }

    const result = await saveOnboarding(data)
    if (result?.error) {
      setError(result.error)
      setSaving(false)
    }
    // On success, server action redirects — no further client action needed
  }

  // ─── Step content ──────────────────────────────────────────────────────────

  function renderStep() {
    switch (step) {
      // ── Step 0: Name ──────────────────────────────────────────────────────
      case 0:
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-3xl font-bold tracking-tight text-gray-900">Hi there!</h2>
              <p className="mt-2 text-lg text-gray-500">What should we call you?</p>
            </div>
            <input
              type="text"
              autoFocus
              value={form.display_name}
              onChange={(e) => set("display_name", e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canProceed()) setStep(1)
              }}
              placeholder="Your name"
              className={cn(
                "w-full border-0 border-b-2 border-gray-200 pb-3 text-2xl font-medium text-gray-900",
                "placeholder-gray-300 focus:border-blue-500 focus:outline-none bg-transparent",
                "transition-colors"
              )}
            />
            <p className="text-sm text-gray-400">
              This is how health will address you — in the app and eventually in voice check-ins.
            </p>
          </div>
        )

      // ── Step 1: About you ─────────────────────────────────────────────────
      case 1:
        return (
          <div className="space-y-7">
            <div>
              <h2 className="text-3xl font-bold tracking-tight text-gray-900">About you</h2>
              <p className="mt-2 text-lg text-gray-500">
                Helps us apply the right reference ranges to your labs.
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">Date of birth</label>
              <FieldInput
                type="date"
                value={form.date_of_birth}
                onChange={(e) => set("date_of_birth", e.target.value)}
                max={new Date().toISOString().split("T")[0]}
              />
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-sm font-medium text-gray-700">Biological sex</label>
                <p className="mt-0.5 text-xs text-gray-400">
                  Used only to apply the correct lab reference ranges.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {(
                  [
                    { value: "male", label: "Male" },
                    { value: "female", label: "Female" },
                    { value: "other", label: "Non-binary / other" },
                    { value: "prefer_not_to_say", label: "Prefer not to say" },
                  ] as const
                ).map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => set("sex", value)}
                    className={cn(
                      "rounded-xl border-2 px-4 py-3 text-sm font-medium transition-all",
                      form.sex === value
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50"
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )

      // ── Step 2: Body metrics ──────────────────────────────────────────────
      case 2:
        return (
          <div className="space-y-7">
            <div>
              <h2 className="text-3xl font-bold tracking-tight text-gray-900">Your body</h2>
              <p className="mt-2 text-lg text-gray-500">
                Baseline metrics for personalised tracking.
              </p>
              <p className="mt-1 text-sm text-gray-400">All optional — skip if you prefer.</p>
            </div>

            {/* Height */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-gray-700">Height</label>
                <UnitToggle
                  options={["cm", "ft"]}
                  value={form.height_unit}
                  onChange={(v) => set("height_unit", v as "cm" | "ft")}
                />
              </div>
              {form.height_unit === "cm" ? (
                <div className="flex items-center gap-3">
                  <FieldInput
                    type="number"
                    value={form.height_cm}
                    onChange={(e) => set("height_cm", e.target.value)}
                    placeholder="170"
                    min={100}
                    max={250}
                  />
                  <span className="text-sm text-gray-500 w-6">cm</span>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <FieldInput
                    type="number"
                    value={form.height_ft}
                    onChange={(e) => set("height_ft", e.target.value)}
                    placeholder="5"
                    min={3}
                    max={8}
                  />
                  <span className="text-sm text-gray-500">ft</span>
                  <FieldInput
                    type="number"
                    value={form.height_in}
                    onChange={(e) => set("height_in", e.target.value)}
                    placeholder="8"
                    min={0}
                    max={11}
                  />
                  <span className="text-sm text-gray-500">in</span>
                </div>
              )}
            </div>

            {/* Weight */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-gray-700">Weight</label>
                <UnitToggle
                  options={["kg", "lbs"]}
                  value={form.weight_unit}
                  onChange={(v) => set("weight_unit", v as "kg" | "lbs")}
                />
              </div>
              <div className="flex items-center gap-3">
                <FieldInput
                  type="number"
                  value={form.weight_display}
                  onChange={(e) => set("weight_display", e.target.value)}
                  placeholder={form.weight_unit === "kg" ? "70" : "155"}
                  min={form.weight_unit === "kg" ? 30 : 66}
                  max={form.weight_unit === "kg" ? 300 : 660}
                />
                <span className="text-sm text-gray-500 w-6">{form.weight_unit}</span>
              </div>
            </div>

            {/* Activity */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">Activity level</label>
              <div className="grid grid-cols-1 gap-2">
                {ACTIVITY_LEVELS.map(({ value, label, desc, emoji }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => set("activity_level", value)}
                    className={cn(
                      "flex items-center gap-4 rounded-xl border-2 px-4 py-2.5 text-left transition-all",
                      form.activity_level === value
                        ? "border-blue-500 bg-blue-50"
                        : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                    )}
                  >
                    <span className="text-xl">{emoji}</span>
                    <div>
                      <p
                        className={cn(
                          "text-sm font-semibold",
                          form.activity_level === value ? "text-blue-700" : "text-gray-900"
                        )}
                      >
                        {label}
                      </p>
                      <p className="text-xs text-gray-400">{desc}</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )

      // ── Step 3: Health conditions ─────────────────────────────────────────
      case 3:
        return (
          <div className="space-y-7">
            <div>
              <h2 className="text-3xl font-bold tracking-tight text-gray-900">Your health</h2>
              <p className="mt-2 text-lg text-gray-500">
                Any conditions we should factor into your insights?
              </p>
              <p className="mt-1 text-sm text-gray-400">
                Optional — you can always add these later from your profile.
              </p>
            </div>

            <div className="space-y-4">
              {/* Severity selector */}
              <div className="flex flex-wrap gap-2">
                {(["mild", "moderate", "severe", "in_remission"] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => set("condition_severity", s)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium transition-all",
                      form.condition_severity === s
                        ? SEVERITY_STYLES[s].ring
                        : "border-gray-200 text-gray-500 hover:border-gray-300"
                    )}
                  >
                    {SEVERITY_LABELS[s]}
                  </button>
                ))}
                <span className="self-center text-xs text-gray-400">severity</span>
              </div>

              {/* Input row */}
              <div className="flex gap-2">
                <FieldInput
                  type="text"
                  value={form.condition_input}
                  onChange={(e) => set("condition_input", e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      addCondition()
                    }
                  }}
                  placeholder="e.g. Type 2 diabetes, hypertension..."
                  className="flex-1"
                />
                <button
                  type="button"
                  onClick={addCondition}
                  disabled={!form.condition_input.trim()}
                  className="rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-30 transition-all"
                >
                  Add
                </button>
              </div>

              {/* Condition chips */}
              {form.conditions.length > 0 && (
                <div className="space-y-2">
                  {form.conditions.map((c, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-3 rounded-xl border border-gray-100 bg-gray-50 px-4 py-3"
                    >
                      <span className="flex-1 text-sm text-gray-900">{c.name}</span>
                      <span
                        className={cn(
                          "rounded-full border px-2.5 py-0.5 text-xs font-medium",
                          SEVERITY_STYLES[c.severity].badge
                        )}
                      >
                        {SEVERITY_LABELS[c.severity]}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeCondition(i)}
                        className="text-gray-400 hover:text-red-500 transition-colors text-lg leading-none"
                        aria-label="Remove condition"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )

      // ── Step 4: Goals & diet ──────────────────────────────────────────────
      case 4:
        return (
          <div className="space-y-7">
            <div>
              <h2 className="text-3xl font-bold tracking-tight text-gray-900">Your goals</h2>
              <p className="mt-2 text-lg text-gray-500">What brings you to health?</p>
              <p className="mt-1 text-sm text-gray-400">Pick everything that applies.</p>
            </div>

            <div className="space-y-6">
              <div>
                <label className="text-sm font-medium text-gray-700">Health goals</label>
                <div className="mt-3 flex flex-wrap gap-2">
                  {HEALTH_GOALS.map((g) => (
                    <Chip
                      key={g}
                      label={g}
                      active={form.health_goals.includes(g)}
                      color="blue"
                      onClick={() => toggleArray("health_goals", g)}
                    />
                  ))}
                </div>
              </div>

              <div>
                <label className="text-sm font-medium text-gray-700">Dietary restrictions</label>
                <div className="mt-3 flex flex-wrap gap-2">
                  {DIETARY_RESTRICTIONS.map((d) => (
                    <Chip
                      key={d}
                      label={d}
                      active={form.dietary_restrictions.includes(d)}
                      color="emerald"
                      onClick={() => toggleArray("dietary_restrictions", d)}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        )

      default:
        return null
    }
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-indigo-50">
      {/* Top progress bar */}
      <div className="fixed inset-x-0 top-0 z-50 h-0.5 bg-gray-100">
        <div
          className="h-full bg-blue-600 transition-all duration-500 ease-out"
          style={{ width: `${((step + 1) / TOTAL_STEPS) * 100}%` }}
        />
      </div>

      <div className="flex min-h-screen items-start justify-center px-4 pb-16 pt-12">
        <div className="w-full max-w-lg">
          {/* Step dots + counter */}
          <div className="mb-6 flex items-center justify-between px-1">
            <div className="flex items-center gap-1.5">
              {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
                <div
                  key={i}
                  className={cn(
                    "rounded-full transition-all duration-300",
                    i < step
                      ? "h-1.5 w-5 bg-blue-500"
                      : i === step
                        ? "h-2 w-2 bg-blue-600"
                        : "h-1.5 w-1.5 bg-gray-200"
                  )}
                />
              ))}
            </div>
            <span className="text-xs font-medium tabular-nums text-gray-400">
              {step + 1} / {TOTAL_STEPS}
            </span>
          </div>

          {/* Card */}
          <div className="rounded-3xl border border-gray-100 bg-white p-8 shadow-xl shadow-gray-100/60">
            {error && (
              <div className="mb-6 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="min-h-[320px]">{renderStep()}</div>

            {/* Navigation */}
            <div className="mt-8 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                className={cn(
                  "text-sm font-medium text-gray-400 hover:text-gray-600 transition-colors",
                  step === 0 && "invisible"
                )}
              >
                ← Back
              </button>

              <div className="flex items-center gap-3">
                {/* Skip only available on optional steps */}
                {step >= 2 && step < TOTAL_STEPS - 1 && (
                  <button
                    type="button"
                    onClick={() => setStep((s) => s + 1)}
                    className="text-sm font-medium text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    Skip
                  </button>
                )}

                {step < TOTAL_STEPS - 1 ? (
                  <button
                    type="button"
                    onClick={() => setStep((s) => s + 1)}
                    disabled={!canProceed()}
                    className={cn(
                      "rounded-xl bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-sm",
                      "hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40 transition-all"
                    )}
                  >
                    Continue →
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={saving}
                    className={cn(
                      "rounded-xl bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-sm",
                      "hover:bg-blue-500 disabled:opacity-50 transition-all"
                    )}
                  >
                    {saving ? "Setting up your profile…" : "Get started →"}
                  </button>
                )}
              </div>
            </div>
          </div>

          <p className="mt-6 text-center text-xs text-gray-400">
            health · your personal health translator
          </p>
        </div>
      </div>
    </div>
  )
}
