-- ============================================================================
-- Headless OBO smoke-test identity (the principal `make status` runs as).
--
-- ENTRA_TEST_USER = svc-triage-test@aniliiitmgmail.onmicrosoft.com is the ROPC test
-- principal. The Entra->Snowflake External OAuth integration maps the token's
-- `upn`/`email` claim to the Snowflake login_name, so:
--   LOGIN_NAME = 'svc-triage-test@aniliiitmgmail.onmicrosoft.com'  (the token upn)
--   user name  (CURRENT_USER()) = SVC_TRIAGE_TEST_ENTRA            (what rls.sql keys on)
--
-- This arrives via user-impersonation (OBO), so it is subject to the ORDERS row
-- access policy and is entitled to ALL regions in rls.sql ('*') so the end-to-end
-- smoke test is not coupled to any one order's region. It is distinct from
-- SVC_ORDER_TRIAGE (the key-pair service user) which the policy whitelists directly.
--
-- Apply as ACCOUNTADMIN (Snowsight) or via the bootstrap admin key-pair, e.g.:
--   make -C bedrock-demo-infra apply-sql FILES="snowflake/smoke_test_user.sql snowflake/rls.sql"
-- ============================================================================

USE ROLE ACCOUNTADMIN;

CREATE USER IF NOT EXISTS SVC_TRIAGE_TEST_ENTRA
  LOGIN_NAME           = 'svc-triage-test@aniliiitmgmail.onmicrosoft.com'
  EMAIL                = 'svc-triage-test@aniliiitmgmail.onmicrosoft.com'
  DEFAULT_ROLE         = ORDER_TRIAGE_RO
  DEFAULT_WAREHOUSE    = ORDER_TRIAGE_WH
  MUST_CHANGE_PASSWORD = FALSE
  COMMENT              = 'OBO smoke-test identity (make status / ENTRA_TEST_USER) - ORDER_TRIAGE_RO, all regions';

GRANT ROLE ORDER_TRIAGE_RO TO USER SVC_TRIAGE_TEST_ENTRA;

-- Verify the External-OAuth mapping resolves to this user:
--   SHOW USERS LIKE 'SVC_TRIAGE_TEST_ENTRA';   -- LOGIN_NAME must equal the token upn
