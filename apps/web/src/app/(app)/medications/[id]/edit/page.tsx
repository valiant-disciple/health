import Link from "next/link"
import { notFound } from "next/navigation"
import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import { MedForm } from "../../_components/med-form"
import { updateMedication } from "../../actions"
import type { MedRow } from "../../actions"

export default async function EditMedicationPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()
  if (!user) redirect("/login")

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { data } = await (supabase as any)
    .from("medications")
    .select("*")
    .eq("id", id)
    .eq("user_id", user.id)
    .single()

  if (!data) notFound()

  const med = data as MedRow

  // Bind the id into the action
  const boundAction = updateMedication.bind(null, id)

  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-6">
        <Link
          href="/medications"
          className="text-xs font-medium text-gray-400 hover:text-gray-600 transition-colors"
        >
          ← Back to medications
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Edit medication</h1>
        <p className="mt-1 text-sm text-gray-500">
          Update dose, frequency, or instructions for {med.name}.
        </p>
      </div>

      <div className="rounded-3xl border border-gray-100 bg-white p-8 shadow-xl shadow-gray-100/60">
        <MedForm
          action={boundAction}
          defaultValues={med}
          submitLabel="Save changes"
          isEdit
        />
      </div>
    </div>
  )
}
