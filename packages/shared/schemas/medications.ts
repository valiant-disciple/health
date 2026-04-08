import { z } from "zod"

export const MedicationSchema = z.object({
  name:                z.string().min(1).max(200),
  rxnorm_code:         z.string().optional(),
  generic_name:        z.string().optional(),
  brand_name:          z.string().optional(),
  dose_amount:         z.number().positive().optional(),
  dose_unit:           z.enum(["mg", "mcg", "g", "units", "mL", "IU", "drops"]).optional(),
  frequency:           z.enum(["once_daily", "twice_daily", "three_times_daily", "four_times_daily", "as_needed", "weekly", "monthly", "other"]).optional(),
  route:               z.enum(["oral", "topical", "inhaled", "subcutaneous", "intravenous", "intramuscular", "nasal", "ophthalmic", "rectal"]).optional(),
  timing:              z.enum(["morning", "afternoon", "evening", "bedtime", "with_meals", "before_meals", "after_meals", "anytime"]).optional(),
  indication:          z.string().max(500).optional(),
  started_date:        z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  status:              z.enum(["active", "paused", "stopped", "as_needed", "unknown"]).default("active"),
  notes:               z.string().max(1000).optional(),
})

export type MedicationInput = z.infer<typeof MedicationSchema>
