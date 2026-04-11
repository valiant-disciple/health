"use client"

import { ResponsiveContainer, LineChart, Line, ReferenceLine, Tooltip } from "recharts"
import { cn } from "@/lib/utils"

const STATUS_COLOR: Record<string, string> = {
  normal:   "#22c55e",
  watch:    "#f59e0b",
  high:     "#f97316",
  low:      "#3b82f6",
  critical: "#ef4444",
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function MiniTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload as { date: string; value: number; status: string }
  return (
    <div className="rounded-lg border border-gray-100 bg-white px-2 py-1 shadow text-xs">
      <p className="text-gray-500">{d.date}</p>
      <p className="font-bold text-gray-900">{d.value}</p>
    </div>
  )
}

export function Sparkline({
  data,
  refLow,
  refHigh,
  currentStatus,
  className,
}: {
  data: Array<{ date: string; value: number; status: string }>
  refLow?: number | null
  refHigh?: number | null
  currentStatus: string
  className?: string
}) {
  if (data.length < 2) {
    return (
      <div className={cn("flex h-12 items-center justify-center rounded-lg bg-gray-50 text-xs text-gray-300", className)}>
        1 reading
      </div>
    )
  }

  const color = STATUS_COLOR[currentStatus] ?? STATUS_COLOR["normal"]!

  return (
    <div className={cn("h-12", className)}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
          {refLow != null && <ReferenceLine y={refLow} stroke="#e5e7eb" strokeDasharray="3 2" strokeWidth={1} />}
          {refHigh != null && <ReferenceLine y={refHigh} stroke="#e5e7eb" strokeDasharray="3 2" strokeWidth={1} />}
          <Tooltip content={<MiniTooltip />} />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: color }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
