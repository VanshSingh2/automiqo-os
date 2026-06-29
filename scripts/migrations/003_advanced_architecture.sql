-- Advanced Architecture Enhancements — migration 003
-- Run in Supabase SQL editor

-- ── KPI Events table ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kpi_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  metric TEXT NOT NULL,
  value NUMERIC NOT NULL,
  department TEXT,
  metadata JSONB DEFAULT '{}',
  recorded_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE kpi_events ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='kpi_events' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON kpi_events FOR ALL USING (true); END IF;
END $$;
CREATE INDEX IF NOT EXISTS kpi_events_metric ON kpi_events(business_id, metric, recorded_at DESC);

-- ── Agent Decisions table (Audit + Capability) ────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  agent_name TEXT NOT NULL,
  decision TEXT NOT NULL,
  workflow TEXT,
  parameters JSONB DEFAULT '{}',
  reason TEXT,
  approved_by TEXT DEFAULT 'autonomous',
  confidence NUMERIC,
  risk_level TEXT DEFAULT 'low',
  decided_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE agent_decisions ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='agent_decisions' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON agent_decisions FOR ALL USING (true); END IF;
END $$;
CREATE INDEX IF NOT EXISTS agent_decisions_agent ON agent_decisions(business_id, agent_name, decided_at DESC);

-- ── Extend audit_log for engines ─────────────────────────────────────────────
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS reasoning TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS confidence NUMERIC;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS approved_by TEXT DEFAULT 'autonomous';
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS risk_level TEXT DEFAULT 'low';
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS outcome TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS workflow TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS parameters JSONB DEFAULT '{}';

-- ── Extend goals for Goal Engine ─────────────────────────────────────────────
ALTER TABLE goals ADD COLUMN IF NOT EXISTS lower_is_better BOOLEAN DEFAULT false;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS unit TEXT DEFAULT 'count';
ALTER TABLE goals ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- ── Extend recommendations for engines ───────────────────────────────────────
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS impact_score NUMERIC;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS confidence NUMERIC;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS engine TEXT;

-- ── Events table for event bus ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  payload JSONB DEFAULT '{}',
  source TEXT,
  listeners_notified TEXT[] DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='events' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON events FOR ALL USING (true); END IF;
END $$;
CREATE INDEX IF NOT EXISTS events_type_biz ON events(business_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS events_recent ON events(business_id, created_at DESC);

-- ── Conversations table ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  contact_phone TEXT,
  lead_id UUID,
  customer_id UUID,
  state TEXT DEFAULT 'new',
  message_count INTEGER DEFAULT 0,
  messages JSONB DEFAULT '[]',
  last_message_at TIMESTAMPTZ,
  last_inbound TEXT,
  booked_at TIMESTAMPTZ,
  booking_url TEXT,
  referral_code TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='conversations' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON conversations FOR ALL USING (true); END IF;
END $$;
CREATE INDEX IF NOT EXISTS conversations_phone ON conversations(business_id, contact_phone);

-- ── Reports type extension ────────────────────────────────────────────────────
-- executive_briefing, nightly_bi_analysis, daily_financial types added automatically

-- ── Indexes for engine queries ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS reflections_mistake ON reflections(business_id, mistake, created_at DESC);
CREATE INDEX IF NOT EXISTS recommendations_engine ON recommendations(business_id, status, generated_by);
CREATE INDEX IF NOT EXISTS reports_type ON reports(business_id, report_type, report_date DESC);
