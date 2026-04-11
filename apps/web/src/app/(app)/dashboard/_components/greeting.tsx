"use client"

import { useMemo } from "react"

export function Greeting({ name }: { name: string | null }) {
  const greeting = useMemo(() => {
    const h = new Date().getHours()
    if (h < 12) return "Good morning"
    if (h < 17) return "Good afternoon"
    return "Good evening"
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">
        {greeting}{name ? `, ${name}` : ""}
      </h1>
      <p className="mt-1 text-sm text-gray-500">Here&apos;s your health overview</p>
    </div>
  )
}
