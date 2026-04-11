# health — Product Requirements Document

> Version 0.2 · Updated 2026-04-10

---

## Vision

Democratise healthcare by giving every person a personal AI health translator that ingests their longitudinal health data — labs, wearables, food, medications, symptoms — and surfaces clear, personalised, actionable insights without requiring medical expertise to interpret.

---

## Core Principles

1. **Longitudinal first** — single timeline of events, never siloed snapshots
2. **Explain, don't alarm** — every insight includes plain-language context and next steps
3. **Privacy by design** — RLS on every table, encrypted at rest, user owns their data
4. **Multimodal input** — PDF, voice, wearable API, manual entry — all first-class citizens
5. **AI-augmented, clinician-compatible** — outputs are shareable with doctors, not a replacement

---

## User Segments

| Segment | Pain point |
|---------|------------|
| Chronic condition patients | Can't interpret their own labs; lose context between appointments |
| Preventive health enthusiasts | Have data (Apple Watch, Oura) but no unified picture |
| Medication-heavy users | Drug interactions and lab interpretations are siloed |
| Health-anxious patients | Need clear "normal / watch / discuss with doctor" triage |

---

## Feature Roadmap

### Phase 1 — Foundation (Days 1–7)

| Day | Feature | Status |
|-----|---------|--------|
| 1 | Auth (Supabase), middleware, Next.js scaffold | ✅ Done |
| 2 | Onboarding wizard (5-step: name → about → body → health → goals) | ✅ Done |
| 3 | Lab report upload (PDF → OCR → structured extraction) | Planned |
| 4 | Medication tracker (CRUD + RxNorm lookup) | ✅ Done |
| 5 | Dashboard (stat cards, timeline) | ✅ Done |
| 6 | AI chat (LangGraph ReAct agent, streaming) | ✅ Done |
| 7 | Lab interpretation view + trend charts | Planned |

### Phase 2 — Intelligence (Days 8–14)

- Wearable ingestion (Apple Health / Google Fit / Fitbit APIs)
- Graphiti bi-temporal knowledge graph for longitudinal reasoning
- Mem0 multi-scope memory (session / user / global medical facts)
- DSPy MIPROv2 optimised prompts for interpretation and chat
- DeepEval / RAGAS CI evaluation pipeline
- LLM Guard (input L1 + output L3) + NeMo guardrails (dialog L2)

### Phase 3 — Scale (Days 15–21)

- Food / nutrition logging (barcode scan, photo, voice)
- Symptom tracker with temporal patterns
- Report sharing (PDF export, provider portal link)
- Referral programme + waitlist

---

## AI Architecture

```
User query
  └─► LLM Guard (L1 input scan)
        └─► NeMo dialog rails (L2 topic gating)
              └─► LangGraph ReAct agent
                    ├─► Tool: search_health_events (Qdrant)
                    ├─► Tool: get_conditions_medications
                    ├─► Tool: retrieve_graph_context (Neo4j / Graphiti)
                    ├─► Tool: get_lab_trends (Postgres)
                    ├─► Tool: search_medical_kb (Qdrant)
                    └─► Tool: mem0_recall
              └─► LLM Guard (L3 output scan)
                    └─► Deterministic critical-value thresholds (L4)
                          └─► Response + citations
```

**Models:** GPT-4o (primary) · GPT-4o-mini (fast / triage)  
**Observability:** Langfuse traces on every LLM call  
**Optimisation:** DSPy MIPROv2 on retrieval + generation pipeline

---

## Voice Onboarding (Future — Phase 3)

### Overview

Replace the current 5-step form wizard with an optional **AI voice call** that conducts the onboarding as a natural conversation. The form and voice paths share the exact same data model and server action — the input channel is the only difference.

### Why

- Onboarding completion rate for voice-first products is typically 2–3× higher than forms
- The current wizard steps (name → about → body → conditions → goals) map 1:1 to natural conversation turns — the architecture is already voice-ready
- Opens the door to a full "weekly health check-in call" feature (Phase 4)

### Proposed Flow

```
User clicks "Start voice onboarding" (or is auto-prompted on mobile)
  └─► WebRTC audio stream → Whisper ASR (transcription)
        └─► GPT-4o Realtime / standard chat — health onboarding agent
              Conducts conversation:
                Turn 1: "Hi! What should I call you?"
                Turn 2: "And what's your date of birth? You can say it naturally."
                Turn 3: "What's your height and weight? Rough estimates are fine."
                Turn 4: "Any health conditions I should know about?"
                Turn 5: "What are you hoping to get out of health?"
              └─► Structured extraction → same OnboardingData type
                    └─► saveOnboarding() server action (shared with form)
                          └─► Redirect to dashboard
```

### Technical Requirements

| Component | Approach |
|-----------|----------|
| ASR | OpenAI Whisper API (or Realtime API for sub-200ms latency) |
| Voice agent | GPT-4o with function calling to fill `OnboardingData` fields |
| TTS response | OpenAI TTS or ElevenLabs for natural-sounding prompts |
| Frontend | WebRTC `getUserMedia()` → chunked upload or WebSocket stream |
| Fallback | Always offer form wizard as fallback (accessibility) |

### Data Contract

Voice path and form path both produce the same `OnboardingData` object and call the same `saveOnboarding()` server action — no backend changes required when voice is added.

### Acceptance Criteria

- [ ] Voice call completes onboarding in < 3 minutes for a typical user
- [ ] All 5 data categories populated (with graceful skip for optional fields)
- [ ] Transcription accuracy ≥ 95% on medical condition names
- [ ] Fallback to form triggered automatically if mic unavailable or user prefers

---

## Data Model (Key Tables)

| Table | Purpose |
|-------|---------|
| `user_profile` | Demographics, body metrics, goals, dietary prefs |
| `health_conditions` | Diagnoses with ICD-10 / SNOMED codes, bi-temporal |
| `health_events` | Universal ledger (LOINC codes) for all modalities |
| `lab_reports` | Raw PDF → OCR → structured |
| `lab_results` | Individual biomarker values with reference ranges |
| `medications` | Active/historical meds, RxNorm coded, bi-temporal |
| `conversations` | Chat history with health agent |
| `messages` | Individual messages with tool call traces |

---

## Security & Compliance

- Row-Level Security enabled on every table
- Supabase Auth (JWT) — all API routes validate session
- LLM Guard scans all LLM inputs and outputs for PHI / PII leakage
- No PHI sent to third-party LLMs beyond the user's own session
- HIPAA-adjacent design (not yet certified — required before scale)

---

## Success Metrics (Phase 1)

| Metric | Target |
|--------|--------|
| Onboarding completion rate | > 70% |
| First lab report uploaded (D+1) | > 40% of onboarded users |
| AI chat DAU / MAU | > 30% |
| Interpretation accuracy (DeepEval) | > 0.85 faithfulness |
| p95 chat latency | < 3 s |
