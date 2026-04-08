// Re-export generated Supabase types
// Run `npm run gen-types` from packages/db after Supabase project is set up

export type { Database } from "./database.generated"

// Convenience row types
export type UserProfile     = import("./database.generated").Database["public"]["Tables"]["user_profile"]["Row"]
export type HealthEvent     = import("./database.generated").Database["public"]["Tables"]["health_events"]["Row"]
export type HealthEventInsert = import("./database.generated").Database["public"]["Tables"]["health_events"]["Insert"]
export type LabReport       = import("./database.generated").Database["public"]["Tables"]["lab_reports"]["Row"]
export type LabResult       = import("./database.generated").Database["public"]["Tables"]["lab_results"]["Row"]
export type Medication      = import("./database.generated").Database["public"]["Tables"]["medications"]["Row"]
export type HealthCondition = import("./database.generated").Database["public"]["Tables"]["health_conditions"]["Row"]
export type Conversation    = import("./database.generated").Database["public"]["Tables"]["conversations"]["Row"]
export type Message         = import("./database.generated").Database["public"]["Tables"]["messages"]["Row"]
export type HealthFact      = import("./database.generated").Database["public"]["Tables"]["health_facts"]["Row"]
