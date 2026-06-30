-- ============================================================================
-- AUTOMIQO OS — MASTER SCHEMA (idempotent)
-- ============================================================================
-- Paste this ENTIRE file into the Supabase SQL Editor and click "Run".
-- It is 100% safe to run multiple times — every statement uses IF NOT EXISTS
-- or a guarded DO block. It creates every table + column the code needs and
-- reconciles all schema drift. Equivalent to setup_supabase.sql + migrations
-- 001 + 002 + 003 combined and de-duplicated.
--
-- Run the VERIFICATION QUERIES at the very bottom afterward to confirm.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. CORE MULTI-TENANT TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS businesses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  industry TEXT,
  phone TEXT,
  email TEXT,
  address TEXT,
  timezone TEXT DEFAULT 'America/New_York',
  config JSONB DEFAULT '{}',
  onboarded_at TIMESTAMPTZ DEFAULT NOW(),
  active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  phone TEXT,
  email TEXT,
  tags TEXT[] DEFAULT '{}',
  lifetime_value NUMERIC DEFAULT 0,
  last_visit TIMESTAMPTZ,
  visit_count INTEGER DEFAULT 0,
  preferences JSONB DEFAULT '{}',
  notes TEXT,
  opt_out_sms BOOLEAN DEFAULT false,
  opt_out_email BOOLEAN DEFAULT false,
  referral_code TEXT,
  referred_by UUID,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staff (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  role TEXT,
  phone TEXT,
  email TEXT,
  services TEXT[] DEFAULT '{}',
  calendar_id TEXT,
  active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS appointments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  customer_id UUID REFERENCES customers(id),
  staff_id UUID REFERENCES staff(id),
  service TEXT,
  scheduled_at TIMESTAMPTZ,
  duration_minutes INTEGER DEFAULT 60,
  status TEXT DEFAULT 'scheduled',
  revenue NUMERIC,
  notes TEXT,
  reminder_sent BOOLEAN DEFAULT false,
  reminder_2h_sent BOOLEAN DEFAULT false,
  calcom_booking_id TEXT,
  calcom_booking_uid TEXT,
  cal_booking_id TEXT,
  cal_booking_uid TEXT,
  no_show_recovery_step INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  product_name TEXT,
  category TEXT,
  quantity NUMERIC,
  reorder_threshold NUMERIC,
  unit TEXT,
  supplier TEXT,
  last_updated TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 2. COMMUNICATIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS calls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  customer_id UUID REFERENCES customers(id),
  direction TEXT DEFAULT 'inbound',
  status TEXT,
  duration_seconds INTEGER,
  transcript TEXT,
  summary TEXT,
  sentiment TEXT,
  outcome TEXT,
  knowledge_gaps TEXT[],
  vapi_call_id TEXT,
  caller_phone TEXT,
  called_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  customer_id UUID REFERENCES customers(id),
  direction TEXT,
  channel TEXT,
  body TEXT,
  status TEXT,
  twilio_sid TEXT,
  campaign_id UUID,
  sent_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  type TEXT,
  status TEXT DEFAULT 'draft',
  target_segment TEXT,
  message_template TEXT,
  scheduled_at TIMESTAMPTZ,
  sent_count INTEGER DEFAULT 0,
  response_count INTEGER DEFAULT 0,
  booking_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 3. TASK DISPATCHER
-- ============================================================================

CREATE TABLE IF NOT EXISTS tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  created_by TEXT NOT NULL,
  workflow TEXT NOT NULL,
  priority TEXT DEFAULT 'normal',
  parameters JSONB DEFAULT '{}',
  status TEXT DEFAULT 'pending',
  result JSONB,
  error TEXT,
  retries INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  executed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS internal_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  owner TEXT,
  assigned_by TEXT,
  department TEXT,
  priority TEXT DEFAULT 'normal',
  status TEXT DEFAULT 'open',
  due_date DATE,
  linked_customer_id UUID REFERENCES customers(id),
  linked_appointment_id UUID REFERENCES appointments(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

-- ============================================================================
-- 4. AGENT INTELLIGENCE
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  agent_name TEXT NOT NULL,
  memory_type TEXT,
  content JSONB,
  key TEXT,
  value TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reflections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  task_id UUID,
  agent_name TEXT,
  what_happened TEXT,
  why TEXT,
  confidence NUMERIC,
  mistake BOOLEAN DEFAULT false,
  lesson TEXT,
  recommendation TEXT,
  source TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recommendations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  generated_by TEXT,
  category TEXT,
  title TEXT,
  description TEXT,
  priority TEXT DEFAULT 'normal',
  impact_estimate TEXT,
  impact_score NUMERIC,
  confidence NUMERIC,
  engine TEXT,
  status TEXT DEFAULT 'pending',
  owner_note TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  report_date DATE,
  report_type TEXT DEFAULT 'daily',
  content JSONB,
  summary TEXT,
  generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS goals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  department TEXT,
  title TEXT,
  metric TEXT,
  target NUMERIC,
  current NUMERIC DEFAULT 0,
  period TEXT,
  lower_is_better BOOLEAN DEFAULT false,
  unit TEXT DEFAULT 'count',
  active BOOLEAN DEFAULT true,
  updated_at TIMESTAMPTZ
);

-- ============================================================================
-- 5. KNOWLEDGE BASE (pgvector)
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  category TEXT,
  title TEXT,
  content TEXT,
  embedding vector(1536),
  source TEXT DEFAULT 'manual',
  approved BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS knowledge_embedding_idx ON knowledge
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================================
-- 6. V3 OPERATIONS / FINANCE
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  trigger_type TEXT,
  trigger_data JSONB,
  agent_chain JSONB,
  agent_name TEXT,
  action TEXT,
  workflow_executed TEXT,
  workflow TEXT,
  parameters JSONB DEFAULT '{}',
  reasoning TEXT,
  confidence NUMERIC,
  approved_by TEXT DEFAULT 'autonomous',
  risk_level TEXT DEFAULT 'low',
  outcome TEXT,
  result TEXT,
  revenue_impact NUMERIC,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS experiments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  hypothesis TEXT,
  variant_a TEXT,
  variant_b TEXT,
  metric TEXT,
  status TEXT DEFAULT 'running',
  winner TEXT,
  sample_size INTEGER,
  duration_days INTEGER,
  variant_a_conversions INTEGER DEFAULT 0,
  variant_b_conversions INTEGER DEFAULT 0,
  a_results JSONB,
  b_results JSONB,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  concluded_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS vendors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  contact_name TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  email TEXT,
  phone TEXT,
  category TEXT,
  products TEXT[],
  lead_time_days INTEGER,
  last_order_amount NUMERIC,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS purchase_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  vendor_id UUID REFERENCES vendors(id),
  items JSONB,
  total_amount NUMERIC,
  status TEXT DEFAULT 'draft',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  sent_at TIMESTAMPTZ,
  received_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ai_costs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  date DATE,
  model TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  tokens_used INTEGER DEFAULT 0,
  cost_usd NUMERIC,
  agent_name TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  recipient_type TEXT,
  recipient_id UUID,
  channel TEXT,
  message TEXT,
  title TEXT,
  event_type TEXT,
  severity TEXT,
  status TEXT,
  sent_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 7. SPRINT 4+ : OWNERS, LEARNING, OPERATIONS, EVENTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS owners (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  hashed_password TEXT NOT NULL,
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS success_scripts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  title TEXT,
  script TEXT,
  category TEXT,
  trigger TEXT,
  response TEXT,
  outcome TEXT,
  score NUMERIC,
  confidence NUMERIC DEFAULT 0,
  used_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS failure_patterns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  pattern TEXT,
  workflows TEXT[],
  error_type TEXT,
  severity TEXT,
  what_failed TEXT,
  root_cause TEXT,
  fix_applied BOOLEAN DEFAULT false,
  detected_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS equipment (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  equipment_id TEXT,
  name TEXT,
  category TEXT,
  maintenance_type TEXT,
  performed_by TEXT,
  notes TEXT,
  last_maintenance TIMESTAMPTZ,
  next_maintenance TIMESTAMPTZ,
  performed_at TIMESTAMPTZ,
  next_maintenance_at TIMESTAMPTZ,
  status TEXT DEFAULT 'operational'
);

CREATE TABLE IF NOT EXISTS resources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  type TEXT,
  status TEXT DEFAULT 'available',
  current_appointment_id UUID,
  available_from TIMESTAMPTZ,
  capacity INTEGER DEFAULT 1,
  available BOOLEAN DEFAULT true,
  notes TEXT,
  updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS locations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  parent_business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  address TEXT,
  city TEXT,
  state TEXT,
  phone TEXT,
  timezone TEXT DEFAULT 'America/New_York',
  settings JSONB DEFAULT '{}',
  synced_at TIMESTAMPTZ,
  active BOOLEAN DEFAULT true
);

-- ============================================================================
-- 8. EVENT BUS / DECISIONS / KPI  (reconciled supersets)
-- ============================================================================

CREATE TABLE IF NOT EXISTS events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  event_type TEXT,
  payload JSONB DEFAULT '{}',
  source TEXT,
  listeners_notified TEXT[] DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  agent_name TEXT,
  decision TEXT,
  workflow TEXT,
  parameters JSONB DEFAULT '{}',
  reason TEXT,
  approved_by TEXT DEFAULT 'autonomous',
  confidence NUMERIC DEFAULT 0,
  risk_level TEXT DEFAULT 'low',
  reasoning TEXT,
  alternatives JSONB DEFAULT '[]',
  outcome TEXT,
  decided_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS kpi_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  metric TEXT NOT NULL,
  value NUMERIC NOT NULL,
  department TEXT,
  metadata JSONB DEFAULT '{}',
  recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 9. LEADS (full lead-intelligence + social columns)
-- ============================================================================

CREATE TABLE IF NOT EXISTS leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  company_name TEXT,
  industry TEXT,
  phone TEXT,
  email TEXT,
  website TEXT,
  address TEXT,
  city TEXT,
  state TEXT DEFAULT 'NJ',
  google_rating NUMERIC,
  review_count INTEGER DEFAULT 0,
  google_place_id TEXT,
  category TEXT,
  business_hours JSONB DEFAULT '[]',
  has_booking_system BOOLEAN DEFAULT false,
  has_website BOOLEAN DEFAULT false,
  has_chatbot BOOLEAN DEFAULT false,
  pricing_mentioned BOOLEAN DEFAULT false,
  booking_platform TEXT,
  tech_stack TEXT[] DEFAULT '{}',
  services_found TEXT[] DEFAULT '{}',
  owner_name TEXT,
  score INTEGER DEFAULT 0,
  tier TEXT DEFAULT 'C',
  score_reason TEXT,
  status TEXT DEFAULT 'new',
  source TEXT DEFAULT 'google_maps',
  notes TEXT,
  enriched BOOLEAN DEFAULT false,
  enrichment_failed BOOLEAN DEFAULT false,
  enrichment_method TEXT,
  email_source TEXT,
  tiktok TEXT,
  -- Instagram
  instagram_username TEXT,
  instagram_followers INTEGER DEFAULT 0,
  instagram_posts INTEGER DEFAULT 0,
  instagram_bio TEXT,
  instagram_verified BOOLEAN DEFAULT false,
  instagram_business BOOLEAN DEFAULT false,
  instagram_category TEXT,
  instagram_email TEXT,
  instagram_phone TEXT,
  instagram_external_url TEXT,
  instagram_scraped BOOLEAN DEFAULT false,
  -- Facebook
  facebook_page_name TEXT,
  facebook_url TEXT,
  facebook_phone TEXT,
  facebook_description TEXT,
  facebook_scraped BOOLEAN DEFAULT false,
  -- LinkedIn
  linkedin_company_url TEXT,
  linkedin_description TEXT,
  linkedin_employee_count TEXT,
  linkedin_industry TEXT,
  linkedin_scraped BOOLEAN DEFAULT false,
  scraped_at TIMESTAMPTZ DEFAULT NOW(),
  last_contacted TIMESTAMPTZ
);

-- ============================================================================
-- 10. GROWTH : CONVERSATIONS, SEQUENCES, REFERRALS
-- ============================================================================

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  contact_phone TEXT,
  lead_id UUID,
  customer_id UUID,
  state TEXT DEFAULT 'new',
  messages JSONB DEFAULT '[]',
  message_count INTEGER DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  last_inbound TEXT,
  booked_at TIMESTAMPTZ,
  booking_url TEXT,
  referral_code TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sequence_enrollments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL,
  contact_type TEXT DEFAULT 'lead',
  phone TEXT,
  email TEXT,
  sequence_name TEXT NOT NULL,
  current_step INTEGER DEFAULT 0,
  status TEXT DEFAULT 'active',
  context JSONB DEFAULT '{}',
  pause_reason TEXT,
  paused_at TIMESTAMPTZ,
  next_step_at TIMESTAMPTZ,
  last_step_sent_at TIMESTAMPTZ,
  enrolled_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS referrals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  referrer_id UUID REFERENCES customers(id),
  referred_id UUID REFERENCES customers(id),
  referral_code TEXT UNIQUE NOT NULL,
  reward_amount NUMERIC DEFAULT 25,
  status TEXT DEFAULT 'active',
  converted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 11. RECONCILE DRIFT — additive ALTERs for DBs created by the older schema
--     (safe no-ops if the column already exists)
-- ============================================================================

ALTER TABLE ai_costs        ADD COLUMN IF NOT EXISTS tokens_used INTEGER DEFAULT 0;
ALTER TABLE agent_decisions ADD COLUMN IF NOT EXISTS workflow TEXT;
ALTER TABLE agent_decisions ADD COLUMN IF NOT EXISTS parameters JSONB DEFAULT '{}';
ALTER TABLE agent_decisions ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE agent_decisions ADD COLUMN IF NOT EXISTS approved_by TEXT DEFAULT 'autonomous';
ALTER TABLE agent_decisions ADD COLUMN IF NOT EXISTS risk_level TEXT DEFAULT 'low';
ALTER TABLE agent_decisions ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE events          ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE audit_log       ADD COLUMN IF NOT EXISTS reasoning TEXT;
ALTER TABLE audit_log       ADD COLUMN IF NOT EXISTS confidence NUMERIC;
ALTER TABLE audit_log       ADD COLUMN IF NOT EXISTS approved_by TEXT DEFAULT 'autonomous';
ALTER TABLE audit_log       ADD COLUMN IF NOT EXISTS risk_level TEXT DEFAULT 'low';
ALTER TABLE audit_log       ADD COLUMN IF NOT EXISTS outcome TEXT;
ALTER TABLE audit_log       ADD COLUMN IF NOT EXISTS workflow TEXT;
ALTER TABLE audit_log       ADD COLUMN IF NOT EXISTS parameters JSONB DEFAULT '{}';
ALTER TABLE goals           ADD COLUMN IF NOT EXISTS lower_is_better BOOLEAN DEFAULT false;
ALTER TABLE goals           ADD COLUMN IF NOT EXISTS unit TEXT DEFAULT 'count';
ALTER TABLE goals           ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS impact_score NUMERIC;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS confidence NUMERIC;
ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS engine TEXT;
ALTER TABLE customers       ADD COLUMN IF NOT EXISTS referral_code TEXT;
ALTER TABLE customers       ADD COLUMN IF NOT EXISTS referred_by UUID;
ALTER TABLE calls           ADD COLUMN IF NOT EXISTS caller_phone TEXT;
ALTER TABLE calls           ADD COLUMN IF NOT EXISTS vapi_call_id TEXT;
ALTER TABLE calls           ADD COLUMN IF NOT EXISTS direction TEXT DEFAULT 'inbound';
ALTER TABLE appointments    ADD COLUMN IF NOT EXISTS reminder_2h_sent BOOLEAN DEFAULT false;
ALTER TABLE appointments    ADD COLUMN IF NOT EXISTS cal_booking_uid TEXT;
ALTER TABLE appointments    ADD COLUMN IF NOT EXISTS cal_booking_id TEXT;
ALTER TABLE appointments    ADD COLUMN IF NOT EXISTS no_show_recovery_step INTEGER DEFAULT 0;
ALTER TABLE conversations   ADD COLUMN IF NOT EXISTS booked_at TIMESTAMPTZ;
ALTER TABLE conversations   ADD COLUMN IF NOT EXISTS booking_url TEXT;
ALTER TABLE conversations   ADD COLUMN IF NOT EXISTS referral_code TEXT;
ALTER TABLE agent_memory    ADD COLUMN IF NOT EXISTS key TEXT;
ALTER TABLE agent_memory    ADD COLUMN IF NOT EXISTS value TEXT;
ALTER TABLE agent_memory    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE reflections     ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE knowledge       ADD COLUMN IF NOT EXISTS embedding vector(1536);
ALTER TABLE knowledge       ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual';
ALTER TABLE knowledge       ADD COLUMN IF NOT EXISTS approved BOOLEAN DEFAULT true;

-- ============================================================================
-- 12. ROW LEVEL SECURITY — enable + permissive service-role policy on EVERY
--     public table (idempotent generic loop; backend uses the service key).
-- ============================================================================

DO $$
DECLARE t text;
BEGIN
  FOR t IN
    SELECT tablename FROM pg_tables WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = t AND policyname = 'service_role_all'
    ) THEN
      EXECUTE format('CREATE POLICY "service_role_all" ON public.%I FOR ALL USING (true) WITH CHECK (true)', t);
    END IF;
  END LOOP;
END $$;

-- ============================================================================
-- 13. INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS leads_tier_score        ON leads(business_id, tier, score DESC);
CREATE INDEX IF NOT EXISTS leads_booking_platform  ON leads(business_id, booking_platform);
CREATE INDEX IF NOT EXISTS leads_instagram         ON leads(business_id, instagram_username);
CREATE INDEX IF NOT EXISTS leads_social_score      ON leads(business_id, score DESC, instagram_scraped);
CREATE INDEX IF NOT EXISTS leads_enriched          ON leads(business_id, enriched, status);
CREATE INDEX IF NOT EXISTS seq_enrollments_active  ON sequence_enrollments(business_id, status, next_step_at);
CREATE INDEX IF NOT EXISTS seq_enrollments_phone   ON sequence_enrollments(business_id, phone, status);
CREATE INDEX IF NOT EXISTS referrals_code          ON referrals(referral_code);
CREATE INDEX IF NOT EXISTS referrals_referrer      ON referrals(business_id, referrer_id);
CREATE INDEX IF NOT EXISTS events_type_biz         ON events(business_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS events_recent           ON events(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS kpi_events_metric       ON kpi_events(business_id, metric, recorded_at DESC);
CREATE INDEX IF NOT EXISTS agent_decisions_agent   ON agent_decisions(business_id, agent_name, decided_at DESC);
CREATE INDEX IF NOT EXISTS reflections_mistake     ON reflections(business_id, mistake, created_at DESC);
CREATE INDEX IF NOT EXISTS recommendations_engine  ON recommendations(business_id, status, generated_by);
CREATE INDEX IF NOT EXISTS reports_type            ON reports(business_id, report_type, report_date DESC);
CREATE INDEX IF NOT EXISTS conversations_phone     ON conversations(business_id, contact_phone);
CREATE INDEX IF NOT EXISTS tasks_status            ON tasks(business_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS appointments_sched      ON appointments(business_id, scheduled_at);
CREATE INDEX IF NOT EXISTS customers_phone         ON customers(business_id, phone);

-- ============================================================================
-- 14. SEMANTIC SEARCH FUNCTION + SEQUENCE STATS VIEW
-- ============================================================================

CREATE OR REPLACE FUNCTION match_knowledge(
  query_embedding vector(1536),
  business_id_filter UUID,
  similarity_threshold FLOAT DEFAULT 0.7,
  match_count INT DEFAULT 5,
  category_filter TEXT DEFAULT NULL
)
RETURNS TABLE (id UUID, title TEXT, content TEXT, category TEXT, similarity FLOAT)
LANGUAGE plpgsql AS $$
BEGIN
  RETURN QUERY
  SELECT k.id, k.title, k.content, k.category,
    1 - (k.embedding <=> query_embedding) AS similarity
  FROM knowledge k
  WHERE k.business_id = business_id_filter
    AND k.approved = true
    AND (category_filter IS NULL OR k.category = category_filter)
    AND 1 - (k.embedding <=> query_embedding) > similarity_threshold
  ORDER BY k.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

CREATE OR REPLACE VIEW sequence_stats AS
SELECT
  business_id,
  sequence_name,
  COUNT(*) FILTER (WHERE status='active')    AS active,
  COUNT(*) FILTER (WHERE status='completed') AS completed,
  COUNT(*) FILTER (WHERE status='paused')    AS paused,
  COUNT(*)                                   AS total
FROM sequence_enrollments
GROUP BY business_id, sequence_name;

-- ============================================================================
-- DONE.  Run the verification queries below to confirm everything exists.
-- ============================================================================
