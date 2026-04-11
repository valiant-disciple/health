"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  LayoutDashboard,
  FlaskConical,
  TrendingUp,
  Pill,
  MessageCircle,
  User,
  Watch,
} from "lucide-react"
import { cn } from "@/lib/utils"

const NAV = [
  { href: "/dashboard",   label: "Dashboard",  icon: LayoutDashboard },
  { href: "/reports",     label: "Lab Reports", icon: FlaskConical },
  { href: "/trends",      label: "Trends",      icon: TrendingUp },
  { href: "/medications", label: "Medications", icon: Pill },
  { href: "/wearables",   label: "Wearables",   icon: Watch },
  { href: "/chat",        label: "Ask health",  icon: MessageCircle },
  { href: "/profile",     label: "Profile",     icon: User },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="flex h-screen w-56 flex-col border-r border-gray-200 bg-white px-3 py-6">
      <Link href="/dashboard" className="mb-8 px-3 text-xl font-bold text-blue-600">
        health
      </Link>
      <nav className="flex flex-1 flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              pathname.startsWith(href)
                ? "bg-blue-50 text-blue-700"
                : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        ))}
      </nav>
    </aside>
  )
}
