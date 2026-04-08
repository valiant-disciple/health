/** Common LOINC codes used throughout the app. */
export const LOINC = {
  // Metabolic
  GLUCOSE:      "2339-0",
  HBA1C:        "4548-4",
  INSULIN:      "20448-7",
  // Lipid panel
  CHOLESTEROL:  "2093-3",
  LDL:          "13457-7",
  HDL:          "2085-9",
  TRIGLYCERIDES:"2571-8",
  // CBC
  WBC:          "6690-2",
  RBC:          "789-8",
  HEMOGLOBIN:   "718-7",
  HEMATOCRIT:   "4544-3",
  PLATELETS:    "777-3",
  // Renal
  CREATININE:   "2160-0",
  BUN:          "3094-0",
  EGFR:         "98979-8",
  // Liver
  AST:          "1920-8",
  ALT:          "2324-2",
  ALP:          "6768-6",
  BILIRUBIN:    "1975-2",
  // Thyroid
  TSH:          "3016-3",
  FREE_T4:      "3024-7",
  FREE_T3:      "3051-0",
  // Electrolytes
  SODIUM:       "2951-2",
  POTASSIUM:    "2823-3",
  CHLORIDE:     "2075-0",
  CO2:          "2028-9",
  // Vitamins & minerals
  VITAMIN_D:    "1989-3",
  VITAMIN_B12:  "2132-9",
  FOLATE:       "2284-8",
  FERRITIN:     "2276-4",
  IRON:         "2498-4",
  MAGNESIUM:    "19123-9",
  // Inflammation
  CRP:          "1988-5",
  ESR:          "4537-7",
  // Hormones
  TESTOSTERONE: "2986-8",
  ESTRADIOL:    "2243-4",
  CORTISOL:     "2143-6",
  // Urine
  URINE_PROTEIN:"21482-5",
  URINE_CREAT:  "2161-8",
} as const

export type LoincCode = (typeof LOINC)[keyof typeof LOINC]

/** Human-readable names for LOINC codes. */
export const LOINC_NAMES: Record<string, string> = {
  [LOINC.GLUCOSE]:      "Glucose",
  [LOINC.HBA1C]:        "HbA1c",
  [LOINC.INSULIN]:      "Insulin",
  [LOINC.CHOLESTEROL]:  "Total Cholesterol",
  [LOINC.LDL]:          "LDL Cholesterol",
  [LOINC.HDL]:          "HDL Cholesterol",
  [LOINC.TRIGLYCERIDES]:"Triglycerides",
  [LOINC.WBC]:          "White Blood Cells",
  [LOINC.RBC]:          "Red Blood Cells",
  [LOINC.HEMOGLOBIN]:   "Hemoglobin",
  [LOINC.HEMATOCRIT]:   "Hematocrit",
  [LOINC.PLATELETS]:    "Platelets",
  [LOINC.CREATININE]:   "Creatinine",
  [LOINC.BUN]:          "BUN",
  [LOINC.EGFR]:         "eGFR",
  [LOINC.AST]:          "AST",
  [LOINC.ALT]:          "ALT",
  [LOINC.ALP]:          "ALP",
  [LOINC.BILIRUBIN]:    "Bilirubin",
  [LOINC.TSH]:          "TSH",
  [LOINC.FREE_T4]:      "Free T4",
  [LOINC.FREE_T3]:      "Free T3",
  [LOINC.SODIUM]:       "Sodium",
  [LOINC.POTASSIUM]:    "Potassium",
  [LOINC.VITAMIN_D]:    "Vitamin D",
  [LOINC.VITAMIN_B12]:  "Vitamin B12",
  [LOINC.FOLATE]:       "Folate",
  [LOINC.FERRITIN]:     "Ferritin",
  [LOINC.IRON]:         "Iron",
  [LOINC.MAGNESIUM]:    "Magnesium",
  [LOINC.CRP]:          "C-Reactive Protein",
  [LOINC.TESTOSTERONE]: "Testosterone",
  [LOINC.ESTRADIOL]:    "Estradiol",
  [LOINC.CORTISOL]:     "Cortisol",
}
