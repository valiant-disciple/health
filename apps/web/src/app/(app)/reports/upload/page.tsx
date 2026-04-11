import { LabUploader } from "./_components/uploader"

export default function UploadPage() {
  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Upload lab report</h1>
        <p className="mt-1 text-sm text-gray-500">
          We&apos;ll extract every test result, map it to standard LOINC codes, and add it to your
          health timeline.
        </p>
      </div>
      <LabUploader />
    </div>
  )
}
