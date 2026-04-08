import { redirect } from "next/navigation"

// Root redirects: logged-in → dashboard, logged-out → login
// Middleware handles auth check; this catches any direct root hits
export default function RootPage() {
  redirect("/login")
}
