import Link from "next/link"
import { notFound } from "next/navigation"
import { getReport } from "../actions"
import { cn } from "@/lib/utils"
import { InterpretButton } from "./_components/interpret-button"
import { InterpretationView } from "./_components/interpretation-view"
import { Sparkline } from "./_components/sparkline"

const STATUS_COLORS: Record<string, { row: string; badge: string }> = {
  normal:   { row: "",              badge: "bg-green-100 text-green-700" },
  high:     { row: "bg-orange-50",  badge: "bg-orange-100 text-orange-700" },
  low:      { row: "bg-blue-50",    badge: "bg-blue-100 text-blue-700" },
  critical: { row: "bg-red-50",     badge: "bg-red-100 text-red-700 font-semibold" },
  watch:    { row: "bg-yellow-50",  badge: "bg-yellow-100 text-yellow-700" },
}

function getColors(status: string | null) {
  return STATUS_COLORS[status ?? "normal"] ?? STATUS_COLORS["normal"]!
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  })
}

export default async function ReportDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const { report, results, interpretation, biomarkerHistory } = await getReport(id)

  if (!report) notFound()

  const isProcessing =
    report.processing_status === "pending" || report.processing_status === "processing"
  const isFailed = report.processing_status === "failed"

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link
            href="/reports"
            className="text-xs font-medium text-gray-400 hover:text-gray-600 transition-colors"
          >
            ← All reports
          </Link>
          <h1 className="mt-2 text-2xl font-bold text-gray-900">
            {report.file_name ?? "Lab Report"}
          </h1>
          {report.report_date && (
            <p className="mt-1 text-sm text-gray-500">
              {report.lab_name ? `${report.lab_name} · ` : ""}
              {formatDate(report.report_date)}
            </p>
          )}
        </div>
        {report.processing_status === "completed" && (
          <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700">
            Ready
          </span>
        )}
      </div>

      {/* Processing state */}
      {isProcessing && (
        <div className="rounded-2xl border border-blue-100 bg-blue-50 p-6 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center">
            <svg className="h-8 w-8 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
          <p className="text-sm font-semibold text-blue-800">Extracting your lab results…</p>
          <p className="mt-1 text-xs text-blue-600">
            This usually takes 15–30 seconds.{" "}
            <Link href={`/reports/${id}`} className="underline">Refresh</Link> to check.
          </p>
        </div>
      )}

      {/* Failed state */}
      {isFailed && (
        <div className="rounded-2xl border border-red-100 bg-red-50 p-6">
          <p className="text-sm font-semibold text-red-800">Processing failed</p>
          <p className="mt-1 text-xs text-red-600">
            We couldn&apos;t extract results from this PDF. Please try re-uploading, or contact support.
          </p>
          <Link
            href="/reports/upload"
            className="mt-3 inline-block rounded-lg bg-red-600 px-4 py-2 text-xs font-semibold text-white hover:bg-red-500"
          >
            Upload again
          </Link>
        </div>
      )}

      {/* Results table */}
      {results.length > 0 && (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900">
              {results.length} result{results.length === 1 ? "" : "s"}
            </h2>
            <div className="flex items-center gap-3 text-xs text-gray-400">
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-green-400" /> Normal
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-orange-400" /> High
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-blue-400" /> Low
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-red-400" /> Critical
              </span>
            </div>
          </div>

          <div className="overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-xs font-medium text-gray-500">
                  <th className="px-4 py-3 text-left">Test</th>
                  <th className="px-4 py-3 text-right">Value</th>
                  <th className="px-4 py-3 text-right">Reference</th>
                  <th className="px-4 py-3 text-center">Status</th>
                  <th className="px-4 py-3 text-center hidden sm:table-cell">Trend</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => {
                  const colors = getColors(r.status)
                  const value = r.value_numeric != null
                    ? `${r.value_numeric}${r.unit ? ` ${r.unit}` : ""}`
                    : (r.value_text ?? "—")
                  const ref = r.ref_range_text
                    ?? (r.ref_range_low != null && r.ref_range_high != null
                        ? `${r.ref_range_low}–${r.ref_range_high}`
                        : "—")
                  const hist = biomarkerHistory[r.loinc_code]

                  return (
                    <tr
                      key={r.id}
                      className={cn(
                        "border-b border-gray-50 last:border-0",
                        i % 2 === 0 ? "" : "bg-gray-50/30",
                        colors.row
                      )}
                    >
                      <td className="px-4 py-3">
                        <p className="font-medium text-gray-900">
                          {r.display_name ?? r.loinc_name}
                        </p>
                        {r.loinc_code && r.loinc_code !== r.loinc_name && (
                          <p className="text-xs text-gray-400">{r.loinc_code}</p>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums text-gray-900">
                        {value}
                      </td>
                      <td className="px-4 py-3 text-right text-xs tabular-nums text-gray-400">
                        {ref}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className={cn("rounded-full px-2 py-0.5 text-xs", colors.badge)}>
                          {r.flag === "H" ? "High" : r.flag === "L" ? "Low" : (r.status ?? "normal")}
                        </span>
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell">
                        {hist && hist.length >= 2 ? (
                          <Sparkline
                            data={hist}
                            refLow={r.ref_range_low}
                            refHigh={r.ref_range_high}
                            currentStatus={r.status ?? "normal"}
                            className="w-24"
                          />
                        ) : (
                          <span className="block text-center text-xs text-gray-300">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-center text-xs text-gray-400">
            LOINC-coded results added to your health timeline
          </p>
        </div>
      )}

      {/* AI interpretation */}
      {report.processing_status === "completed" && (
        <div className="space-y-4">
          {interpretation ? (
            <InterpretationView
              interpretation={interpretation}
              biomarkerHistory={biomarkerHistory}
            />
          ) : (
            <div className="rounded-2xl border border-dashed border-gray-200 bg-gray-50/40 p-6 text-center">
              <p className="mb-4 text-sm text-gray-500">
                Get a personalised AI breakdown of your results — findings, dietary tips, medication flags, and what to discuss with your doctor.
              </p>
              <InterpretButton reportId={id} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
