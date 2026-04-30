# WhatsApp Biomarker Bot

A WhatsApp-native assistant that helps users **understand** their blood reports —
what each biomarker measures, why a value might be high or low, and how findings
might connect to symptoms they've shared.

> Not a doctor. Not a diagnosis. An interpretation layer between a confused person
> and the dense table of numbers their lab handed back.

## Architecture (single-page tour)

```
WhatsApp user
    │
    ▼ Twilio webhook
┌────────────────────┐    ┌───────────────────────┐
│  main.py (FastAPI) │    │ Postgres (Supabase)   │
│  • verify sig      │───▶│ • users, reports,     │
│  • idempotency     │    │   biomarker_results,  │
│  • rate limit      │    │   conversations,      │
│  • enqueue         │    │   user_facts          │
└────────────────────┘    │ • message_queue       │
                          └───────────┬───────────┘
                                      │ poll
                                      ▼
                          ┌───────────────────────┐
                          │  worker.py            │
                          │  ┌─────────────────┐  │
                          │  │  handlers.py    │  │
                          │  │   ├ OCR         │──┼─→ Mistral OCR + GPT-4o vision
                          │  │   ├ orchestr.py │──┼─→ OpenAI (gpt-4o + tools)
                          │  │   ├ guardrails  │  │
                          │  │   └ Twilio reply│──┼─→ WhatsApp user
                          │  └─────────────────┘  │
                          └───────────────────────┘
```

**Web** (FastAPI) and **worker** are two separate processes deployed as separate
Render services. Both connect to the same Supabase Postgres.

## Tech stack

| Layer | Tool |
|---|---|
| Hosting | Render (web service + background worker) |
| Postgres + storage + queue | Supabase (`ap-south-1`) |
| Cache | Upstash Redis (REST) — kept lightweight |
| LLM | OpenAI (GPT-4o orchestrator, GPT-4o-mini extractor) |
| OCR | Mistral OCR primary → GPT-4o vision fallback → pypdf for searchable PDFs |
| WhatsApp | Twilio (sandbox during dev, production approval pending) |
| Errors | Sentry |
| Logs | structlog → Render |

## Project layout

```
apps/whatsapp-agent/
├── main.py            FastAPI webhook receiver
├── worker.py          Background worker (polls message_queue)
├── handlers.py        process_text + process_media — full business logic
├── orchestrator.py    Single-LLM tool-calling loop
├── tools.py           Tool schemas + dispatcher (lab history, facts, etc.)
├── ocr.py             pypdf → Mistral OCR → vision fallback chain
├── llm.py             OpenAI client wrapper (retries, cost tracking)
├── memory.py          Context builder + fact extraction
├── biomarkers.py      Loads supported_biomarkers.json, alias matching, tiering
├── guardrails.py      All 8 guardrail layers
├── prompts.py         All system prompts in one place (versioned)
├── jobs.py            Postgres-backed message queue (renamed from queue.py
│                       to avoid stdlib shadow)
├── storage.py         Supabase Storage upload + signed URL
├── twilio_client.py   Twilio REST + signature verify
├── db.py              asyncpg pool + helpers
├── crypto.py          Phone hashing + AES-GCM PII encrypt
├── redis_client.py    Upstash Redis REST (lightly used)
├── config.py          pydantic-settings
├── data/
│   └── supported_biomarkers.json   152 biomarkers with tier classification
├── migrations/
│   ├── 001_schema.sql      All tables, indices, triggers
│   ├── 002_rls.sql          Row-Level Security policies
│   └── 003_storage.sql      Bucket setup
├── scripts/
│   ├── setup_db.py                    Runs migrations
│   ├── setup_storage.py               Creates bucket
│   └── build_supported_biomarkers.py  Regenerates the static biomarker JSON
├── render.yaml         Render blueprint (web + worker)
├── Dockerfile          Used by Render or `docker run` locally
├── requirements.txt
└── .env.example
```

## What the bot answers

### Supported (Tier 1 — full interpretation)
- "What does HDL mean?"
- "Why is my LDL high?"
- "Compare my last two reports"
- "Is my HbA1c improving?"
- Upload a PDF → get an interpretation per biomarker with prior-context recall

### Specialist deferral (Tier 2)
- Tumor markers (PSA, CA-125, CEA): definition + "discuss with oncologist"
- Autoimmune (ANA, RF): "discuss with rheumatologist"
- Advanced cardiac (troponin, BNP): "this is emergency-territory, see cardiology"
- Specialised hormones (testosterone panels, etc.): "endocrinologist"

### Hard refused
- Genetic test results
- Pathology / biopsy reports
- Imaging reports (X-ray, CT, MRI, ultrasound, ECG)
- Pap smears / cytology

### Always refused
- Diagnoses ("do I have X?")
- Prescriptions ("should I take metformin?")
- Dosage advice
- Emergency symptoms → emergency-services redirect
- Crisis (self-harm) → crisis hotline numbers

## Memory model

We give the LLM three layers of context on every turn:
1. **Long-term summary** — `users.conversation_summary`, regenerated when
   conversation grows past 30 turns.
2. **Structured facts** — `user_facts` rows (symptoms, conditions, lifestyle)
   extracted via a small JSON-LLM call after each exchange.
3. **Lab history** — recent `biomarker_results` (last 180 days), grouped by
   report date, included in compact form.

Plus the last 10 conversation turns as raw messages.

This is why the bot can say "remember when I told you LDL is the bad
cholesterol last month? Yours has come down — that's real progress."

## Guardrails

8 layers, all in `guardrails.py`:

1. **Input validation** — file type, size, message length, sender format
2. **Rate limiting** — Postgres sliding window, per-phone (10/min, 200/day, 30 PDFs/day)
3. **Idempotency** — Twilio MessageSid dedupe so retries don't double-process
4. **Prompt-injection sanitation** — strip "ignore previous", system-impersonation
   patterns from OCR text; user content wrapped in `<user_message>` tags
5. **Moderation** — OpenAI moderation API on every user input
6. **Emergency detection** — keyword matching for medical emergencies + crisis signals
7. **Output validation** — block diagnostic claims, require doctor disclaimer,
   strip PII, cap length
8. **Cost caps** — per-user daily spend cap + global kill switch

## Local development

```bash
cd apps/whatsapp-agent

# 1. Python env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Copy env, fill in credentials
cp .env.example .env
# then edit .env — minimum needed: TWILIO_*, OPENAI_API_KEY, SUPABASE_*,
# PHONE_HASH_PEPPER (generate with `openssl rand -hex 32`)

# 3. Apply migrations
python scripts/setup_db.py

# 4. Create the storage bucket
python scripts/setup_storage.py

# 5. Run web + worker in two terminals
python main.py                     # webhook receiver on :8000
python worker.py                   # in another terminal

# 6. Expose to Twilio (sandbox dev)
ngrok http 8000
# point your Twilio sandbox webhook at https://<ngrok>.ngrok.app/whatsapp
```

## Deployment to Render

1. Push this repo to GitHub.
2. In Render, "New > Blueprint" → point at `render.yaml`.
3. In the env-group `whatsapp-bot-prod`, add the secrets:
   - `PUBLIC_BASE_URL` → your Render web URL
   - `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`
   - `OPENAI_API_KEY`, `MISTRAL_API_KEY`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL`, `SUPABASE_POOLER_URL`
   - `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`
   - `PHONE_HASH_PEPPER`, `PII_ENCRYPTION_KEY`
   - `SENTRY_DSN` (optional)
4. Run `python scripts/setup_db.py` once locally with the production DSN to apply
   migrations (or use Supabase's SQL editor).
5. Update Twilio webhook URL to `https://<your-render-host>/whatsapp`.

## Security checklist before public launch

- [ ] Rotate API keys that were ever shared in chat / commits
- [ ] WhatsApp Business API approval (move off sandbox)
- [ ] Privacy policy + Terms of Service drafted by lawyer
- [ ] Medical disclaimer added to onboarding + every report
- [ ] Penetration test on the webhook surface
- [ ] Sentry alerting configured + tested
- [ ] Cost dashboards live (per-user + global)
- [ ] Cloudflare in front for WAF + DDOS

## Known limits / TODO

- WhatsApp **sandbox only** in dev — users must opt in by texting a sandbox code.
  Production launch needs WA Business API approval.
- **Single worker** — fine for closed beta, scale horizontally by running
  multiple instances. The `FOR UPDATE SKIP LOCKED` pattern handles concurrency.
- **No conversational pictures yet** — we OCR images but don't return diagrams
  back (could add charts of biomarker trends).
- **English-only prompts** — `preferred_language` field exists, prompts don't
  branch on it yet.
- **Knowledge graph not used at runtime** — by design (see PRD); collected
  data is KG-ready (LOINC codes, structured facts) for future expansion.

## Cost model (rough, per active user / month)

Assuming an avg user sends 10 messages and 1 PDF per month:

| Item | Cost |
|---|---|
| OpenAI GPT-4o orchestrator (10 msgs × ~$0.005) | $0.05 |
| OpenAI GPT-4o-mini fact extraction (10 × $0.0002) | $0.002 |
| Mistral OCR (1 PDF × ~$0.003) | $0.003 |
| GPT-4o-mini structuring (1 × $0.001) | $0.001 |
| Twilio WhatsApp (~10 outbound × $0.005) | $0.05 |
| Supabase storage + DB | ~$0 at this scale |
| **Total per active user / month** | **≈ $0.10** |

Render web $7 + worker $7 + Supabase free + Upstash free + LLM/Twilio per-user
gets the first 1000 active users for ~$120-150/mo all-in.
