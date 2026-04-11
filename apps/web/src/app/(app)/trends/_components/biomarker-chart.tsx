"use client"

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts"
import { cn } from "@/lib/utils"
import type { BiomarkerSeries } from "../actions"

const STATUS_COLOR: Record<string, string> = {
  normal:   "#22c55e",
  watch:    "#f59e0b",
  high:     "#f97316",
  low:      "#3b82f6",
  critical: "#ef4444",
}

const TREND_ICON: Record<string, string> = {
  improving:     "↗",
  worsening:     "↘",
  stable:        "→",
  first_reading: "•",
}

const STATUS_BADGE: Record<string, string> = {
  normal:   "bg-green-100 text-green-700",
  watch:    "bg-yellow-100 text-yellow-700",
  high:     "bg-orange-100 text-orange-700",
  low:      "bg-blue-100 text-blue-700",
  critical: "bg-red-100 text-red-700",
}

function CustomDot(props: {
  cx?: number
  cy?: number
  payload?: { status: string }
  index?: number
  dataLength?: number
}) {
  const { cx, cy, payload, index, dataLength } = props
  if (cx == null || cy == null) return null
  const color = STATUS_COLOR[payload?.status ?? "normal"] ?? STATUS_COLOR["normal"]!
  const isLast = index === (dataLength ?? 0) - 1
  return (
    <circle
      cx={cx}
      cy={cy}
      r={isLast ? 5 : 3}
      fill={color}
      stroke="white"
      strokeWidth={isLast ? 2 : 1}
    />
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload as { date: string; value: number; status: string }
  return (
    <div className="rounded-xl border border-gray-100 bg-white px-3 py-2 shadow-lg text-xs">
      <p className="font-medium text-gray-700">{d.date}</p>
      <p className="text-base font-bold text-gray-900">{d.value}</p>
      <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", STATUS_BADGE[d.status] ?? STATUS_BADGE["normal"])}>
        {d.status}
      </span>
    </div>
  )
}

export function BiomarkerChart({ series }: { series: BiomarkerSeries }) {
  const lineColor = STATUS_COLOR[series.latestStatus] ?? STATUS_COLOR["normal"]!
  const dataWithLength = series.readings.map((r) => ({ ...r, dataLength: series.readings.length }))

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-5 shadow-sm">
      {/* Header */}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{series.name}</h3>
          <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
            <span>{series.readings.length} reading{series.readings.length === 1 ? "" : "s"}</span>
            {series.unit && <><span>·</span><span>{series.unit}</span></>}
            {series.refLow != null && series.refHigh != null && (
              <><span>·</span><span>ref {series.refLow}–{series.refHigh}</span></>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span
            className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold tabular-nums", STATUS_BADGE[series.latestStatus] ?? STATUS_BADGE["normal"])}
          >
            {series.latest} {series.unit ?? ""}
          </span>
          <span
            title={series.trend}
            className="text-sm font-bold"
            style={{ color: lineColor }}
          >
            {TREND_ICON[series.trend]}
          </span>
        </div>
      </div>

      {/* Chart */}
      {series.readings.length === 1 ? (
        <div className="flex h-20 items-center justify-center rounded-xl bg-gray-50">
          <p className="text-xs text-gray-400">Only 1 reading — chart available after 2+</p>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={dataWithLength} margin={{ top: 5, right: 5, left: -30, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              tickFormatter={(d: string) => {
                const [, m, day] = d.split("-")
                return `${m}/${day}`
              }}
            />
            <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} domain={["auto", "auto"]} />
            <Tooltip content={<CustomTooltip />} />
            {series.refLow != null && (
              <ReferenceLine y={series.refLow} stroke="#d1d5db" strokeDasharray="4 2" />
            )}
            {series.refHigh != null && (
              <ReferenceLine y={series.refHigh} stroke="#d1d5db" strokeDasharray="4 2" />
            )}
            <Line
              type="monotone"
              dataKey="value"
              stroke={lineColor}
              strokeWidth={2}
              dot={(props) => <CustomDot {...props} dataLength={series.readings.length} />}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
