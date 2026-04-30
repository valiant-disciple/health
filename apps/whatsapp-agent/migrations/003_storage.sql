-- ════════════════════════════════════════════════════════════════════════════
-- Migration 003: Storage bucket setup
-- ════════════════════════════════════════════════════════════════════════════
-- Run AFTER creating the bucket via Supabase dashboard or:
--   curl -X POST "$SUPABASE_URL/storage/v1/bucket" ...
-- This enforces RLS on storage.objects.
-- ════════════════════════════════════════════════════════════════════════════

INSERT INTO storage.buckets (id, name, public)
VALUES ('lab-reports', 'lab-reports', false)
ON CONFLICT (id) DO NOTHING;

-- Server-only access via service_role key.
-- No policies for anon/authenticated → no client-side access at all.
-- Signed URLs (generated server-side with service_role) are how we serve
-- PDFs back to users via Twilio media_url.
