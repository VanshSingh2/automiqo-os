-- ============================================================================
-- Migration 004 — Business OS modules: reviews, expenses, HR, shifts
-- Idempotent. Safe to run multiple times. Paste into Supabase SQL editor.
-- ============================================================================

-- ── Reputation: reviews ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  platform TEXT,
  author TEXT,
  rating NUMERIC,
  text TEXT,
  sentiment TEXT,
  dedup_key TEXT,
  responded BOOLEAN DEFAULT false,
  response_text TEXT,
  review_date TEXT,
  ingested_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Accounting: expenses ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS expenses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  amount NUMERIC NOT NULL,
  category TEXT,
  tax_category TEXT,
  description TEXT,
  vendor TEXT,
  expense_date DATE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── HR: applicants ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS applicants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  role TEXT,
  email TEXT,
  phone TEXT,
  resume_text TEXT,
  stage TEXT DEFAULT 'applied',
  screen_score NUMERIC,
  screen_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── HR: shifts ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS shifts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  staff_id UUID REFERENCES staff(id),
  starts_at TIMESTAMPTZ,
  ends_at TIMESTAMPTZ,
  role TEXT,
  status TEXT DEFAULT 'scheduled',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── staff: certifications for HR cert-expiry tracking ─────────────────────
ALTER TABLE staff ADD COLUMN IF NOT EXISTS certifications JSONB DEFAULT '[]';

-- ── inventory: supplier already exists; ensure reorder fields present ──────
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reorder_threshold NUMERIC;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS supplier TEXT;

-- ── RLS + permissive service-role policy on the new tables ────────────────
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['reviews','expenses','applicants','shifts']
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                   WHERE schemaname='public' AND tablename=t AND policyname='service_role_all') THEN
      EXECUTE format('CREATE POLICY "service_role_all" ON public.%I FOR ALL USING (true) WITH CHECK (true)', t);
    END IF;
  END LOOP;
END $$;

-- ── Indexes ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS reviews_biz_sentiment ON reviews(business_id, sentiment, responded);
CREATE INDEX IF NOT EXISTS reviews_dedup        ON reviews(business_id, dedup_key);
CREATE INDEX IF NOT EXISTS expenses_biz_date    ON expenses(business_id, expense_date DESC);
CREATE INDEX IF NOT EXISTS applicants_biz_stage ON applicants(business_id, stage);
CREATE INDEX IF NOT EXISTS shifts_biz_start     ON shifts(business_id, starts_at);
