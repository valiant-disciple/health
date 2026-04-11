"use client"

import { useActionState, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { uploadLabReport } from "../../actions"

export function LabUploader() {
  const [state, formAction, pending] = useActionState(uploadLabReport, null)
  const [dragging, setDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file && inputRef.current) {
      const dt = new DataTransfer()
      dt.items.add(file)
      inputRef.current.files = dt.files
      setSelectedFile(file)
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    setSelectedFile(e.target.files?.[0] ?? null)
  }

  const fileSizeMB = selectedFile ? (selectedFile.size / 1024 / 1024).toFixed(1) : null

  return (
    <form action={formAction} className="space-y-6">
      {/* Error */}
      {state?.error && (
        <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{state.error}</div>
      )}

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "relative flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-8 py-14 text-center transition-all",
          dragging
            ? "border-blue-400 bg-blue-50"
            : selectedFile
              ? "border-green-400 bg-green-50"
              : "border-gray-200 bg-gray-50 hover:border-blue-300 hover:bg-blue-50/40"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          name="file"
          accept="application/pdf"
          onChange={handleFileChange}
          className="sr-only"
        />

        {selectedFile ? (
          <>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-100">
              <svg className="h-6 w-6 text-green-600" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-900">{selectedFile.name}</p>
              <p className="mt-0.5 text-xs text-gray-500">{fileSizeMB} MB · PDF</p>
            </div>
            <p className="text-xs text-gray-400">Click to change file</p>
          </>
        ) : (
          <>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-100">
              <svg className="h-6 w-6 text-blue-600" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m6.75 12l-3-3m0 0l-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-700">
                {dragging ? "Drop your PDF here" : "Drop your lab report PDF"}
              </p>
              <p className="mt-0.5 text-xs text-gray-400">or click to browse · up to 20 MB</p>
            </div>
          </>
        )}
      </div>

      {/* Info */}
      <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3">
        <p className="text-sm font-medium text-blue-800">What happens next</p>
        <ol className="mt-1.5 space-y-1 text-xs text-blue-600">
          <li>1. Your PDF is securely uploaded and encrypted</li>
          <li>2. Our AI extracts every test result with LOINC codes</li>
          <li>3. Results are added to your health timeline</li>
          <li>4. You get a plain-English interpretation on the report page</li>
        </ol>
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={!selectedFile || pending}
        className={cn(
          "w-full rounded-xl bg-blue-600 px-6 py-3.5 text-sm font-semibold text-white shadow-sm",
          "hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40 transition-all"
        )}
      >
        {pending ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Uploading...
          </span>
        ) : (
          "Upload and analyse →"
        )}
      </button>
    </form>
  )
}
