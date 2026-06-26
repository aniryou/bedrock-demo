-- ============================================================================
-- Semantic view for the order-triage demo — the business model Cortex Analyst
-- reads to turn natural-language questions into governed SQL over ORDERS/CUSTOMERS.
--
-- This is what replaced the snowflake_stub's four hand-written SQL templates: the
-- agent's tool is now a single `ask {question}` that calls Cortex Analyst against
-- ORDERS_SV, then runs the generated SQL as the signed-in user. Row security is
-- unchanged — the row-access policy on ORDERS.region (snowflake/rls.sql) is enforced
-- at the base table, so queries through this view are scoped per user by construction.
--
-- Idempotent (CREATE OR REPLACE) + safe to re-run. Apply with the bootstrap admin
-- AFTER setup.sql (CREATE OR REPLACE TABLE rebuilds ORDERS/CUSTOMERS and would drop a
-- dependent view), e.g.:
--   make -C bedrock-demo-infra apply-sql \
--     FILES="snowflake/rls.sql snowflake/semantic_view.sql snowflake/test_user.sql"
--
-- NOTE: CREATE SEMANTIC VIEW is GA but its grammar is exact — validate this DDL against
-- the live account on first apply (Snowflake reports column/clause errors precisely).
-- ============================================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE ORDER_TRIAGE_DB;
USE SCHEMA PUBLIC;

-- ── Cross-region inference (PREREQUISITE — confirm before relying on /ask) ───────────
-- The account is ap-southeast-1; Cortex Analyst's LLM is not served in every region, so
-- generation needs cross-region inference enabled (APJ routes to ap-northeast-1). This is
-- an ACCOUNT-WIDE setting with data-egress/region implications — review and uncomment
-- deliberately (or set it once out-of-band). 'ANY_REGION' is the broadest; 'AWS_APJ' keeps
-- inference within Asia-Pacific.
-- ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_APJ';

-- ── The semantic view ────────────────────────────────────────────────────────────────
-- Logical tables map to the physical ORDERS/CUSTOMERS; facts are row-level numerics,
-- dimensions are the who/what/where/when to group + filter by, metrics are the governed
-- aggregations. Synonyms/comments are the NL aliases that help Analyst map language -> model.
CREATE OR REPLACE SEMANTIC VIEW ORDER_TRIAGE_DB.PUBLIC.ORDERS_SV
  TABLES (
    orders AS ORDER_TRIAGE_DB.PUBLIC.ORDERS
      PRIMARY KEY (order_id)
      WITH SYNONYMS ('sales orders', 'tickets')
      COMMENT = 'Customer orders to triage',
    customers AS ORDER_TRIAGE_DB.PUBLIC.CUSTOMERS
      PRIMARY KEY (customer_id)
      WITH SYNONYMS ('accounts', 'clients')
      COMMENT = 'Customer accounts (master data)'
  )
  RELATIONSHIPS (
    order_customer AS orders (customer_id) REFERENCES customers (customer_id)
  )
  FACTS (
    orders.amount AS amount,
    customers.credit_limit AS credit_limit
  )
  DIMENSIONS (
    orders.order_id AS order_id,
    orders.status AS status WITH SYNONYMS ('order state'),
    orders.channel AS channel WITH SYNONYMS ('sales channel'),
    orders.region AS region WITH SYNONYMS ('order region'),
    orders.created_at AS created_at WITH SYNONYMS ('order date'),
    customers.customer_id AS customer_id,
    customers.customer_name AS name WITH SYNONYMS ('account name', 'customer name'),
    customers.tier AS tier WITH SYNONYMS ('segment', 'customer tier'),
    customers.customer_region AS region
  )
  METRICS (
    orders.total_amount AS SUM(orders.amount) WITH SYNONYMS ('order value', 'revenue'),
    orders.order_count AS COUNT(orders.order_id) WITH SYNONYMS ('number of orders'),
    orders.avg_order_value AS AVG(orders.amount)
  )
  COMMENT = 'Order-triage semantic model for Cortex Analyst (orders joined to customers).';

-- ── Grants ───────────────────────────────────────────────────────────────────────────
-- Consumers (Cortex Analyst + direct SQL) need SELECT on the semantic view itself; the
-- read-only role already has SELECT on the underlying tables (setup.sql). ORDER_TRIAGE_RO
-- is the role of BOTH the service user (SVC_ORDER_TRIAGE) and the impersonated OBO humans,
-- so this one grant covers every read path.
GRANT SELECT ON SEMANTIC VIEW ORDER_TRIAGE_DB.PUBLIC.ORDERS_SV TO ROLE ORDER_TRIAGE_RO;

-- Cortex functions require the SNOWFLAKE.CORTEX_USER database role. It is granted to PUBLIC
-- by default; (re)grant to the read-only role so /ask works even if that default was revoked.
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE ORDER_TRIAGE_RO;

-- ── Verify ───────────────────────────────────────────────────────────────────────────
--   SHOW SEMANTIC VIEWS IN SCHEMA ORDER_TRIAGE_DB.PUBLIC;
--   SELECT * FROM SEMANTIC_VIEW(
--     ORDER_TRIAGE_DB.PUBLIC.ORDERS_SV
--     DIMENSIONS orders.region
--     METRICS    orders.total_amount, orders.order_count
--   );   -- as ANIL_ENTRA => only Europe; as SVC_ORDER_TRIAGE => all regions (RLS holds)
