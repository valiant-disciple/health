-- Supabase seed file
-- Run after all migrations to set up Supabase Storage buckets and policies

-- Create Storage bucket for lab reports
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'lab-reports',
  'lab-reports',
  false,                        -- private bucket
  10485760,                     -- 10MB max file size
  ARRAY['application/pdf', 'image/jpeg', 'image/png', 'image/heic', 'image/webp']
)
ON CONFLICT (id) DO NOTHING;

-- RLS: users can only access their own lab report files
-- Path convention: {user_id}/{report_id}.pdf
CREATE POLICY "Users can upload own lab reports"
  ON storage.objects FOR INSERT
  WITH CHECK (
    bucket_id = 'lab-reports'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );

CREATE POLICY "Users can read own lab reports"
  ON storage.objects FOR SELECT
  USING (
    bucket_id = 'lab-reports'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );

CREATE POLICY "Users can delete own lab reports"
  ON storage.objects FOR DELETE
  USING (
    bucket_id = 'lab-reports'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );
