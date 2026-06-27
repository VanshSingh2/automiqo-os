-- ============================================
-- CORE MULTI-TENANT TABLES
-- ============================================

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

-- ============================================
-- COMMUNICATIONS
-- ============================================

CREATE TABLE IF NOT EXISTS calls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  customer_id UUID REFERENCES customers(id),
  direction TEXT,
  status TEXT,
  duration_seconds INTEGER,
  transcript TEXT,
  summary TEXT,
  sentiment TEXT,
  outcome TEXT,
  knowledge_gaps TEXT[],
  vapi_call_id TEXT,
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

-- ============================================
-- TASK DISPATCHER
-- ============================================

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

-- ============================================
-- AGENT INTELLIGENCE
-- ============================================

CREATE TABLE IF NOT EXISTS agent_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  agent_name TEXT NOT NULL,
  memory_type TEXT,
  content JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reflections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  task_id UUID REFERENCES tasks(id),
  agent_name TEXT,
  what_happened TEXT,
  why TEXT,
  confidence NUMERIC,
  mistake BOOLEAN DEFAULT false,
  lesson TEXT,
  recommendation TEXT,
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
  active BOOLEAN DEFAULT true
);

-- ============================================
-- KNOWLEDGE BASE (pgvector)
-- ============================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  category TEXT,
  title TEXT,
  content TEXT,
  embedding vector(1536),
  source TEXT,
  approved BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS knowledge_embedding_idx ON knowledge
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================
-- ROW LEVEL SECURITY
-- ============================================

ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE reflections ENABLE ROW LEVEL SECURITY;
ALTER TABLE recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE goals ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON businesses FOR ALL USING (true);
CREATE POLICY "service_role_all" ON customers FOR ALL USING (true);
CREATE POLICY "service_role_all" ON staff FOR ALL USING (true);
CREATE POLICY "service_role_all" ON appointments FOR ALL USING (true);
CREATE POLICY "service_role_all" ON inventory FOR ALL USING (true);
CREATE POLICY "service_role_all" ON calls FOR ALL USING (true);
CREATE POLICY "service_role_all" ON messages FOR ALL USING (true);
CREATE POLICY "service_role_all" ON campaigns FOR ALL USING (true);
CREATE POLICY "service_role_all" ON tasks FOR ALL USING (true);
CREATE POLICY "service_role_all" ON agent_memory FOR ALL USING (true);
CREATE POLICY "service_role_all" ON reflections FOR ALL USING (true);
CREATE POLICY "service_role_all" ON recommendations FOR ALL USING (true);
CREATE POLICY "service_role_all" ON reports FOR ALL USING (true);
CREATE POLICY "service_role_all" ON goals FOR ALL USING (true);
CREATE POLICY "service_role_all" ON knowledge FOR ALL USING (true);

-- ============================================
-- v3 ADDITIONS
-- ============================================

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

CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  trigger_type TEXT,
  trigger_data JSONB,
  agent_chain JSONB,
  workflow_executed TEXT,
  result TEXT,
  revenue_impact NUMERIC,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS experiments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  variant_a TEXT,
  variant_b TEXT,
  metric TEXT,
  status TEXT DEFAULT 'running',
  winner TEXT,
  a_results JSONB,
  b_results JSONB,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS vendors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  name TEXT,
  contact_name TEXT,
  email TEXT,
  phone TEXT,
  products TEXT[],
  lead_time_days INTEGER,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
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
  status TEXT,
  sent_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE internal_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiments ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendors ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_costs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications_log ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='internal_tasks' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON internal_tasks FOR ALL USING (true); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='audit_log' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON audit_log FOR ALL USING (true); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='experiments' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON experiments FOR ALL USING (true); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='vendors' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON vendors FOR ALL USING (true); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='purchase_orders' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON purchase_orders FOR ALL USING (true); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='ai_costs' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON ai_costs FOR ALL USING (true); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='notifications_log' AND policyname='service_role_all') THEN
    CREATE POLICY "service_role_all" ON notifications_log FOR ALL USING (true); END IF;
END $$;
