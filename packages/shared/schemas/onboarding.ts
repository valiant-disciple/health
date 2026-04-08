import { z } from "zod"

export const OnboardingStep1Schema = z.object({
  display_name:   z.string().min(1).max(100),
  date_of_birth:  z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Use YYYY-MM-DD format"),
  sex:            z.enum(["male", "female", "other", "prefer_not_to_say"]),
  height_cm:      z.number().min(50).max(300).optional(),
  weight_kg:      z.number().min(10).max(500).optional(),
  activity_level: z.enum(["sedentary", "light", "moderate", "active", "very_active"]),
})

export const OnboardingStep2Schema = z.object({
  health_conditions: z.array(
    z.object({
      name:         z.string().min(1),
      icd10_code:   z.string().optional(),
      severity:     z.enum(["mild", "moderate", "severe", "in_remission"]).optional(),
      diagnosed_at: z.string().optional(),
    })
  ).max(20),
})

export const OnboardingStep3Schema = z.object({
  medications: z.array(
    z.object({
      name:         z.string().min(1),
      dose_amount:  z.number().positive().optional(),
      dose_unit:    z.string().optional(),
      frequency:    z.enum(["once_daily", "twice_daily", "three_times_daily", "as_needed", "weekly", "other"]).optional(),
      indication:   z.string().optional(),
      started_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    })
  ).max(30),
})

export const OnboardingStep4Schema = z.object({
  dietary_restrictions: z.array(
    z.enum([
      "vegetarian", "vegan", "gluten_free", "lactose_intolerant",
      "nut_allergy", "halal", "kosher", "low_sodium", "diabetic_diet",
      "low_fodmap", "keto", "paleo",
    ])
  ),
  food_preferences: z.object({
    cuisines_enjoyed: z.array(z.string()).optional(),
    foods_disliked:   z.array(z.string()).optional(),
    cooking_skill:    z.enum(["none", "basic", "intermediate", "advanced"]).optional(),
  }).optional(),
})

export const OnboardingStep5Schema = z.object({
  health_goals: z.array(
    z.enum([
      "weight_loss", "muscle_gain", "manage_diabetes", "manage_hypertension",
      "improve_cholesterol", "increase_energy", "improve_sleep",
      "reduce_inflammation", "general_wellness", "athletic_performance",
    ])
  ).min(1).max(5),
  timezone: z.string().default("UTC"),
})

export type OnboardingStep1 = z.infer<typeof OnboardingStep1Schema>
export type OnboardingStep2 = z.infer<typeof OnboardingStep2Schema>
export type OnboardingStep3 = z.infer<typeof OnboardingStep3Schema>
export type OnboardingStep4 = z.infer<typeof OnboardingStep4Schema>
export type OnboardingStep5 = z.infer<typeof OnboardingStep5Schema>
