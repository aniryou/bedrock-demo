-- ============================================================================
-- Second test user for the multi-user OBO demo (the "denied" user, User B).
--
-- Mirrors ANIL_ENTRA (User A). The Entra→Snowflake External OAuth integration
-- maps the token's `upn`/`email` claim to the Snowflake login_name, so:
--   LOGIN_NAME  = the second Entra principal's UPN (jince@aniliiitmgmail.onmicrosoft.com).
--               jince is a native MEMBER user, so it HAS a upn (unlike the personal
--               admin, which had to be mapped by email).
--   user name   (CURRENT_USER()) = JINCE_ENTRA — this is what RLS keys on, so it
--               must match the snowflake_user value seeded in rls.sql.
--
-- Grants the SAME read-only role as User A (ORDER_TRIAGE_RO). The DIFFERENCE in
-- what they see comes purely from the row access policy (rls.sql), keyed on
-- ORDERS.region: User A (ANIL_ENTRA) is entitled to Europe, User B (JINCE_ENTRA)
-- to Asia → each sees only their own region's orders (neither sees Africa/NA).
-- Customers stay visible to both (CUSTOMERS is unpoliced + customer reads use the
-- agent identity).
--
-- Apply as ACCOUNTADMIN (Snowsight) or via the bootstrap admin key-pair.
-- ============================================================================

USE ROLE ACCOUNTADMIN;

CREATE USER IF NOT EXISTS JINCE_ENTRA
  LOGIN_NAME           = 'jince@aniliiitmgmail.onmicrosoft.com'
  EMAIL                = 'jince@aniliiitmgmail.onmicrosoft.com'
  DEFAULT_ROLE         = ORDER_TRIAGE_RO
  DEFAULT_WAREHOUSE    = ORDER_TRIAGE_WH
  MUST_CHANGE_PASSWORD = FALSE
  COMMENT              = 'OBO demo user B - granted ORDER_TRIAGE_RO, RLS-denied orders';

GRANT ROLE ORDER_TRIAGE_RO TO USER JINCE_ENTRA;

-- Verify the External-OAuth mapping will resolve to this user:
--   SHOW USERS LIKE 'JINCE_ENTRA';   -- check LOGIN_NAME matches the token upn/email
