import Link from "next/link"
import { cn } from "@/lib/utils"

interface StatCardProps {
  title: string
  value: string | number
  subtitle: string
  href: string
  accent?: "blue" | "green" | "orange" | "red" | "purple"
  badge?: { label: string; variant: "pulse" | "static" } | undefined
  icon: React.ReactNode
}

const ACCENT: Record<NonNullable<StatCardProps["accent"]>, { bg: string; icon: string; value: string }> = {
  blue:   { bg: "bg-blue-50",   icon: "text-blue-500",   value: "text-blue-700" },
  green:  { bg: "bg-green-50",  icon: "text-green-500",  value: "text-green-700" },
  orange: { bg: "bg-orange-50", icon: "text-orange-500", value: "text-orange-700" },
  red:    { bg: "bg-red-50",    icon: "text-red-500",    value: "text-red-700" },
  purple: { bg: "bg-purple-50", icon: "text-purple-500", value: "text-purple-700" },
}

export function StatCard({ title, value, subtitle, href, accent = "blue", badge, icon }: StatCardProps) {
  const colors = ACCENT[accent]

  return (
    <Link
      href={href}
      className="group relative flex flex-col gap-3 rounded-2xl border border-gray-100 bg-white p-5 shadow-sm transition-all hover:shadow-md hover:-translate-y-0.5"
    >
      <div className="flex items-start justify-between">
        <div className={cn("flex h-10 w-10 items-center justify-center rounded-xl", colors.bg)}>
          <span className={colors.icon}>{icon}</span>
        </div>
        {badge && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-xs font-medium",
              badge.variant === "pulse"
                ? "animate-pulse bg-orange-100 text-orange-700"
                : "bg-gray-100 text-gray-600"
            )}
          >
            {badge.label}
          </span>
        )}
      </div>

      <div>
        <p className={cn("text-3xl font-bold tabular-nums", colors.value)}>{value}</p>
        <p className="mt-0.5 text-sm font-medium text-gray-600">{title}</p>
        <p className="mt-0.5 text-xs text-gray-400">{subtitle}</p>
      </div>

      <span className="absolute right-4 bottom-4 text-xs font-medium text-gray-300 transition-colors group-hover:text-gray-500">
        View →
      </span>
    </Link>
  )
}
