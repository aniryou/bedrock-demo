-- ============================================================================
-- Row-level security for the multi-user OBO demo — REGION-scoped.
--
-- A ROW ACCESS POLICY on ORDERS so that, under user-impersonation, each human
-- sees only the order REGIONS their Snowflake identity is entitled to — while:
--   * the agent's own service identity (SVC_ORDER_TRIAGE) sees ALL regions
--     (so the primary SigV4 runtime + agent-authority reads are unaffected), and
--   * CUSTOMERS stays UNPOLICED (agent-default customer access).
--
-- Current entitlement: ANIL_ENTRA -> Europe, JINCE_ENTRA -> Asia (each human sees
-- only their own region; NEITHER sees Africa / NA); SVC_TRIAGE_TEST_ENTRA -> '*'
-- (the OBO smoke-test identity, all regions). Edit the USER_REGION_ACCESS rows
-- below to change this; a user may have multiple regions, and '*' = all.
--
-- Idempotent + safe to re-run. Apply with the bootstrap admin AFTER setup.sql
-- (CREATE OR REPLACE TABLE ORDERS drops the attached policy), e.g.:
--   make -C bedrock-demo-infra apply-sql FILES="snowflake/rls.sql snowflake/test_user.sql"
-- ============================================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE ORDER_TRIAGE_DB;
USE SCHEMA PUBLIC;

-- 1) Region entitlement: which Snowflake user may see which order regions.
CREATE TABLE IF NOT EXISTS ORDER_TRIAGE_DB.PUBLIC.USER_REGION_ACCESS (
  snowflake_user STRING NOT NULL,   -- matches CURRENT_USER()
  region         STRING NOT NULL,   -- Asia | Africa | Europe | NA   ('*' = all)
  note           STRING
);

-- Seed the demo entitlements (idempotent: clear the demo users, then re-insert).
DELETE FROM ORDER_TRIAGE_DB.PUBLIC.USER_REGION_ACCESS
 WHERE snowflake_user IN ('ANIL_ENTRA', 'JINCE_ENTRA', 'SVC_TRIAGE_TEST_ENTRA');
INSERT INTO ORDER_TRIAGE_DB.PUBLIC.USER_REGION_ACCESS (snowflake_user, region, note) VALUES
  ('ANIL_ENTRA',            'Europe', 'demo user A: Europe only'),
  ('JINCE_ENTRA',           'Asia',   'demo user B: Asia only'),
  ('SVC_TRIAGE_TEST_ENTRA', '*',      'OBO smoke-test identity (make status): all regions');

-- 2) The row access policy (keyed on ORDERS.region). The body runs as the policy
--    OWNER, so it reads USER_REGION_ACCESS regardless of the querying role.
--    Detach first so CREATE OR REPLACE is safe; then (re)create + attach.
ALTER TABLE ORDER_TRIAGE_DB.PUBLIC.ORDERS DROP ALL ROW ACCESS POLICIES;

CREATE OR REPLACE ROW ACCESS POLICY ORDER_TRIAGE_DB.PUBLIC.orders_region_rap
  AS (region STRING) RETURNS BOOLEAN ->
       -- the agent's own service identity sees ALL regions
       CURRENT_USER() = 'SVC_ORDER_TRIAGE'
       -- impersonated humans: only their entitled region(s)
    OR EXISTS (
         SELECT 1
           FROM ORDER_TRIAGE_DB.PUBLIC.USER_REGION_ACCESS m
          WHERE m.snowflake_user = CURRENT_USER()
            AND (m.region = '*' OR m.region = region)
       );

ALTER TABLE ORDER_TRIAGE_DB.PUBLIC.ORDERS
  ADD ROW ACCESS POLICY ORDER_TRIAGE_DB.PUBLIC.orders_region_rap ON (region);

-- 3) Remove the legacy customer-id-based policy + table (replaced by region).
DROP ROW ACCESS POLICY IF EXISTS ORDER_TRIAGE_DB.PUBLIC.orders_rap;
DROP TABLE IF EXISTS ORDER_TRIAGE_DB.PUBLIC.USER_ORDER_ACCESS;

-- ── Verify ───────────────────────────────────────────────────────────────────
--   as SVC_ORDER_TRIAGE      => all 12 orders (every region)
--   as ANIL_ENTRA            => only the 5 Europe orders
--   as JINCE_ENTRA           => only the 5 Asia orders
--   as SVC_TRIAGE_TEST_ENTRA => all 12 orders (smoke-test identity, '*')
