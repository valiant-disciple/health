export default function ReportDetailPage({ params }: { params: { id: string } }) {
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">Report {params.id}</h1>
      <p className="mt-1 text-sm text-gray-500">Day 5 — interpretation view coming</p>
    </div>
  )
}
