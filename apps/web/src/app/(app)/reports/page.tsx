import Link from "next/link"
import { getReports } from "./actions"
import { cn } from "@/lib/utils"

const STATUS_BADGE: Record<string, { label: string; class: string }> = {
  pending:    { label: "Queued",      class: "bg-gray-100 text-gray-600" },
  processing: { label: "Processing…", class: "bg-blue-100 text-blue-700 animate-pulse" },
  completed:  { label: "Ready",       class: "bg-green-100 text-green-700" },
  failed:     { label: "Failed",      class: "bg-red-100 text-red-700" },
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

export default async function ReportsPage() {
  const reports = await getReports()

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Lab Reports</h1>
          <p className="mt-1 text-sm text-gray-500">
            {reports.length === 0
              ? "No reports yet"
              : `${reports.length} report${reports.length === 1 ? "" : "s"}`}
          </p>
        </div>
        <Link
          href="/reports/upload"
          className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 transition-colors"
        >
          + Upload PDF
        </Link>
      </div>

      {/* Empty state */}
      {reports.length === 0 && (
        <div className="rounded-2xl border-2 border-dashed border-gray-200 py-16 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50">
            <svg className="h-6 w-6 text-blue-500" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
          </div>
          <h3 className="mt-4 text-sm font-semibold text-gray-900">No lab reports yet</h3>
          <p className="mt-1 text-sm text-gray-500">Upload your first PDF to get started.</p>
          <Link
            href="/reports/upload"
            className="mt-4 inline-block rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 transition-colors"
          >
            Upload report
          </Link>
        </div>
      )}

      {/* Report list */}
      {reports.length > 0 && (
        <div className="space-y-3">
          {reports.map((r) => {
            const badge = (STATUS_BADGE[r.processing_status] ?? STATUS_BADGE["pending"])!
            const isReady = r.processing_status === "completed"

            return (
              <div
                key={r.id}
                className="flex items-center gap-4 rounded-2xl border border-gray-100 bg-white p-4 shadow-sm transition hover:shadow-md"
              >
                {/* File icon */}
                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-blue-50">
                  <svg className="h-5 w-5 text-blue-500" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                  </svg>
                </div>

                {/* Info */}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-gray-900">
                    {r.file_name ?? "Unnamed report"}
                  </p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {r.lab_name ? `${r.lab_name} · ` : ""}
                    {r.report_date
                      ? formatDate(r.report_date)
                      : `Uploaded ${formatDate(r.created_at)}`}
                  </p>
                </div>

                {/* Status badge */}
                <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-medium", badge.class)}>
                  {badge.label}
                </span>

                {/* Action */}
                {isReady && (
                  <Link
                    href={`/reports/${r.id}`}
                    className="rounded-lg border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 transition-colors"
                  >
                    View →
                  </Link>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Refresh hint for in-progress */}
      {reports.some((r) => r.processing_status === "processing" || r.processing_status === "pending") && (
        <p className="text-center text-xs text-gray-400">
          Reports are processing in the background.{" "}
          <Link href="/reports" className="underline hover:text-gray-600">Refresh</Link> to check status.
        </p>
      )}
    </div>
  )
}
