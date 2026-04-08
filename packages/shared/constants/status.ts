export type HealthStatus = "normal" | "watch" | "discuss" | "high" | "low" | "critical"

export const STATUS_CONFIG: Record<
  HealthStatus,
  { label: string; color: string; bg: string; border: string; priority: number }
> = {
  normal:   { label: "Normal",   color: "text-green-700",  bg: "bg-green-50",   border: "border-green-200",  priority: 0 },
  watch:    { label: "Watch",    color: "text-yellow-700", bg: "bg-yellow-50",  border: "border-yellow-200", priority: 1 },
  low:      { label: "Low",      color: "text-blue-700",   bg: "bg-blue-50",    border: "border-blue-200",   priority: 2 },
  discuss:  { label: "Discuss",  color: "text-orange-700", bg: "bg-orange-50",  border: "border-orange-200", priority: 3 },
  high:     { label: "High",     color: "text-red-700",    bg: "bg-red-50",     border: "border-red-200",    priority: 4 },
  critical: { label: "Critical", color: "text-purple-700", bg: "bg-purple-50",  border: "border-purple-200", priority: 5 },
}

export const MEDICATION_FREQUENCIES: Record<string, string> = {
  once_daily:         "Once daily",
  twice_daily:        "Twice daily",
  three_times_daily:  "Three times daily",
  four_times_daily:   "Four times daily",
  as_needed:          "As needed",
  weekly:             "Weekly",
  monthly:            "Monthly",
  other:              "Other",
}

export const ACTIVITY_LEVELS: Record<string, string> = {
  sedentary: "Sedentary (desk job, little exercise)",
  light:     "Light (1-3 days/week exercise)",
  moderate:  "Moderate (3-5 days/week exercise)",
  active:    "Active (6-7 days/week exercise)",
  very_active: "Very Active (intense daily exercise)",
}
