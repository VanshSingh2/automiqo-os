-- Lead Intelligence Engine + Free Scraping System — schema additions
-- Run in Supabase SQL editor

-- ── Lead Intelligence Engine columns ────────────────────────────────────────
ALTER TABLE leads ADD COLUMN IF NOT EXISTS tech_stack TEXT[] DEFAULT '{}';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS booking_platform TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS has_chatbot BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS pricing_mentioned BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS tiktok TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS owner_name TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS services_found TEXT[] DEFAULT '{}';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS tier TEXT DEFAULT 'C';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS business_hours JSONB DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS google_place_id TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS enriched BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS enrichment_failed BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_source TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS city TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS state TEXT DEFAULT 'NJ';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS score_reason TEXT;

-- ── Free Scraping System — social media columns ──────────────────────────────

-- Instagram
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_username TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_followers INTEGER DEFAULT 0;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_posts INTEGER DEFAULT 0;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_bio TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_verified BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_business BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_category TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_email TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_phone TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_external_url TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_scraped BOOLEAN DEFAULT false;

-- Facebook
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_page_name TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_url TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_phone TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_description TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_scraped BOOLEAN DEFAULT false;

-- LinkedIn
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_company_url TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_description TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_employee_count TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_industry TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_scraped BOOLEAN DEFAULT false;

-- Enrichment metadata
ALTER TABLE leads ADD COLUMN IF NOT EXISTS enrichment_method TEXT;
-- values: 'scrapling' | 'crawl4ai' | 'scrapling_partial'

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS leads_tier_score ON leads(business_id, tier, score DESC);
CREATE INDEX IF NOT EXISTS leads_booking_platform ON leads(business_id, booking_platform);
CREATE INDEX IF NOT EXISTS leads_instagram ON leads(business_id, instagram_username);
CREATE INDEX IF NOT EXISTS leads_social_score ON leads(business_id, score DESC, instagram_scraped);
CREATE INDEX IF NOT EXISTS leads_enriched ON leads(business_id, enriched, status);
