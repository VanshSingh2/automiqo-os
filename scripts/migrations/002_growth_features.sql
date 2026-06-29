-- Growth Features Migration: nurture sequences, referrals, outbound calls
-- Run in Supabase SQL editor

-- ── Nurture Sequence Enrollments ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sequence_enrollments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL,
  contact_type TEXT DEFAULT 'lead',       -- 'lead' | 'customer'
  phone TEXT,
  email TEXT,
  sequence_name TEXT NOT NULL,            -- 'cold_lead' | 'warm_lead' | 'post_visit' | 'no_show' | 'win_back'
  current_step INTEGER DEFAULT 0,
  status TEXT DEFAULT 'active',           -- 'active' | 'paused' | 'completed' | 'dead'
  context JSONB DEFAULT '{}',             -- {name, company, industry, booking_url}
  pause_reason TEXT,
  paused_at TIMESTAMPTZ,
  next_step_at TIMESTAMPTZ,
  last_step_sent_at TIMESTAMPTZ,
  enrolled_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);
ALTER TABLE sequence_enrollments ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='sequence_enrollments' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON sequence_enrollments FOR ALL USING (true); END IF;
END $$;
CREATE INDEX IF NOT EXISTS seq_enrollments_active ON sequence_enrollments(business_id, status, next_step_at);
CREATE INDEX IF NOT EXISTS seq_enrollments_phone ON sequence_enrollments(business_id, phone, status);

-- ── Referrals ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referrals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  referrer_id UUID REFERENCES customers(id),
  referred_id UUID REFERENCES customers(id),
  referral_code TEXT UNIQUE NOT NULL,
  reward_amount NUMERIC DEFAULT 25,
  status TEXT DEFAULT 'active',           -- 'active' | 'converted' | 'expired'
  converted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE referrals ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='referrals' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON referrals FOR ALL USING (true); END IF;
END $$;
CREATE INDEX IF NOT EXISTS referrals_code ON referrals(referral_code);
CREATE INDEX IF NOT EXISTS referrals_referrer ON referrals(business_id, referrer_id);

-- ── Outbound calls log (extend existing calls table) ─────────────────────────
ALTER TABLE calls ADD COLUMN IF NOT EXISTS vapi_call_id TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS caller_phone TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS direction TEXT DEFAULT 'inbound';

-- ── Appointments: cal.com booking UID ────────────────────────────────────────
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS cal_booking_uid TEXT;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS cal_booking_id TEXT;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS no_show_recovery_step INTEGER DEFAULT 0;

-- ── Customers: referral + sequence tracking ───────────────────────────────────
ALTER TABLE customers ADD COLUMN IF NOT EXISTS referral_code TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS referred_by UUID REFERENCES customers(id);

-- ── Conversations: add referral tracking ─────────────────────────────────────
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS referral_code TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS booked_at TIMESTAMPTZ;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS booking_url TEXT;

-- ── Events bus: add new event types to index ─────────────────────────────────
CREATE INDEX IF NOT EXISTS events_type_business ON events(business_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS events_recent ON events(business_id, created_at DESC);

-- ── Sequence stats view ───────────────────────────────────────────────────────
CREATE OR REPLACE VIEW sequence_stats AS
SELECT
  business_id,
  sequence_name,
  COUNT(*) FILTER (WHERE status='active') AS active,
  COUNT(*) FILTER (WHERE status='completed') AS completed,
  COUNT(*) FILTER (WHERE status='paused') AS paused,
  COUNT(*) AS total
FROM sequence_enrollments
GROUP BY business_id, sequence_name;
