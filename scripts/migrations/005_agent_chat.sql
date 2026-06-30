-- ============================================================================
-- Migration 005 — Agent team chat (group chat between CEO / dept heads / managers)
-- Idempotent. Safe to run multiple times. Paste into Supabase SQL editor.
--
-- The "team chat" is the human-readable conversation between agents.
-- The "backstage" feed is derived on read from the existing `events` table,
-- so it needs no table of its own.
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
  channel TEXT NOT NULL DEFAULT 'team',     -- 'team' (group chat) | 'dm'
  from_agent TEXT NOT NULL,                  -- "CEO", "COO", "Inventory Manager", "Owner"
  from_role TEXT,                            -- 'executive' | 'department' | 'manager' | 'owner'
  to_agent TEXT,                             -- optional target ("team" or a specific agent)
  message TEXT NOT NULL,
  category TEXT DEFAULT 'update',            -- 'update'|'alert'|'decision'|'question'|'standup'
  urgency TEXT DEFAULT 'normal',             -- 'low'|'normal'|'high'
  related_event_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS agent_messages_biz_time
  ON agent_messages(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS agent_messages_biz_channel
  ON agent_messages(business_id, channel, created_at DESC);

-- ── RLS + permissive service-role policy (backend uses service key) ────────
DO $$
BEGIN
  EXECUTE 'ALTER TABLE public.agent_messages ENABLE ROW LEVEL SECURITY';
  IF NOT EXISTS (SELECT 1 FROM pg_policies
                 WHERE schemaname='public' AND tablename='agent_messages'
                   AND policyname='service_role_all') THEN
    EXECUTE 'CREATE POLICY "service_role_all" ON public.agent_messages FOR ALL USING (true) WITH CHECK (true)';
  END IF;
END $$;
