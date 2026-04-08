import { z } from "zod"

export const LabFindingSchema = z.object({
  loinc:          z.string(),
  name:           z.string(),
  value:          z.string(),
  status:         z.enum(["normal", "watch", "discuss", "high", "low", "critical"]),
  explanation:    z.string(),
  trend:          z.enum(["improving", "worsening", "stable", "first_reading"]),
  previous_value: z.string().nullable(),
  previous_date:  z.string().nullable(),
})

export const DietarySuggestionSchema = z.object({
  category:  z.enum(["increase", "decrease", "avoid", "add"]),
  suggestion: z.string(),
  mechanism: z.string(),
  foods:     z.array(z.string()),
  priority:  z.enum(["high", "medium", "low"]),
})

export const ReportInterpretationSchema = z.object({
  summary:              z.string(),
  key_findings:         z.array(LabFindingSchema),
  dietary_suggestions:  z.array(DietarySuggestionSchema),
  lifestyle_suggestions: z.array(z.object({
    category:   z.string(),
    suggestion: z.string(),
    mechanism:  z.string(),
    priority:   z.enum(["high", "medium", "low"]),
  })),
  drug_nutrient_flags: z.array(z.object({
    medication:  z.string(),
    depletes:    z.string(),
    interaction: z.string(),
    suggestion:  z.string(),
    severity:    z.enum(["major", "moderate", "minor"]),
  })),
  discuss_with_doctor: z.array(z.object({
    finding: z.string(),
    reason:  z.string(),
    urgency: z.enum(["routine", "soon", "urgent"]),
  })),
  context_used: z.object({
    conditions_count:     z.number(),
    medications_count:    z.number(),
    recent_results_count: z.number(),
    health_facts_count:   z.number(),
  }),
})

export type LabFinding          = z.infer<typeof LabFindingSchema>
export type DietarySuggestion   = z.infer<typeof DietarySuggestionSchema>
export type ReportInterpretation = z.infer<typeof ReportInterpretationSchema>
