-- Snowflake bootstrap for the order-triage demo (run by `make snowflake-setup`).
-- Object names (ORDER_TRIAGE_WH/DB/RO, SVC_ORDER_TRIAGE) are the defaults; to rename,
-- set SNOWFLAKE_WAREHOUSE/DATABASE/RO_ROLE/SVC_USER and let scripts/snowflake_bootstrap.py
-- substitute them here (do NOT edit names only here — the secret payload comes from those vars).
-- Idempotent and safe to re-run. Creates the warehouse / DB / schema / tables,
-- seeds the sample orders + customers, and creates a read-only role + key-pair
-- service user. The service user's RSA public key is registered separately by
-- scripts/snowflake_bootstrap.py (it generates the key-pair and stores the private
-- key + connection config in AWS Secrets Manager). Do NOT put a key here.

USE ROLE ACCOUNTADMIN;

-- Pay-per-use warehouse: XSMALL, suspends after 60s idle, auto-resumes on query.
CREATE WAREHOUSE IF NOT EXISTS ORDER_TRIAGE_WH
  WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS ORDER_TRIAGE_DB;
CREATE SCHEMA   IF NOT EXISTS ORDER_TRIAGE_DB.PUBLIC;

-- CREATE OR REPLACE reseeds the demo data to a known state on every run.
CREATE OR REPLACE TABLE ORDER_TRIAGE_DB.PUBLIC.ORDERS (
  order_id    STRING       NOT NULL,
  customer_id STRING       NOT NULL,
  amount      NUMBER(12,2) NOT NULL,
  status      STRING       NOT NULL,
  channel     STRING,
  region      STRING,                 -- Asia | Africa | Europe | NA  (RLS row-access key)
  created_at  DATE
);

CREATE OR REPLACE TABLE ORDER_TRIAGE_DB.PUBLIC.CUSTOMERS (
  customer_id  STRING       NOT NULL,
  name         STRING,
  tier         STRING,
  region       STRING,
  credit_limit NUMBER(12,2)
);

-- 12 orders across Asia/Africa/Europe/NA. Under RLS (snowflake/rls.sql) the two
-- demo humans see only their entitled region — JINCE_ENTRA -> Asia, ANIL_ENTRA ->
-- Europe — each with its own low/medium/high risk mix; Africa + NA are visible to
-- NEITHER human (only the agent's service identity). Risk = order_risk_score(amount
-- vs the customer's credit_limit, tier, channel).
INSERT INTO ORDER_TRIAGE_DB.PUBLIC.ORDERS
  (order_id, customer_id, amount, status, channel, region, created_at) VALUES
  ('O-1001','C-001',12000 ,'OPEN'     ,'web'    ,'Asia'  ,'2026-06-01'),  -- low    (Jince/Asia)
  ('O-1002','C-002',48000 ,'OPEN'     ,'partner','Europe','2026-06-03'),  -- high   (Anil/Europe)
  ('O-1003','C-003',45000 ,'OPEN'     ,'web'    ,'Asia'  ,'2026-06-05'),  -- high   (Jince/Asia)
  ('O-1004','C-001',250000,'OPEN'     ,'partner','Asia'  ,'2026-06-06'),  -- medium (Jince/Asia)
  ('O-1005','C-005',15000 ,'SHIPPED'  ,'web'    ,'NA'    ,'2026-05-20'),  -- low    (hidden/NA)
  ('O-1006','C-006',22000 ,'OPEN'     ,'web'    ,'Asia'  ,'2026-06-10'),  -- high   (Jince/Asia)
  ('O-1007','C-004',5000  ,'CLOSED'   ,'web'    ,'Europe','2026-05-01'),  -- low    (Anil/Europe)
  ('O-1008','C-002',52000 ,'OPEN'     ,'partner','Europe','2026-06-12'),  -- high   (Anil/Europe)
  ('O-1009','C-003',8000  ,'CANCELLED','web'    ,'Europe','2026-04-15'),  -- medium (Anil/Europe)
  ('O-1010','C-005',180000,'OPEN'     ,'partner','Africa','2026-06-14'),  -- high   (hidden/Africa)
  ('O-1011','C-001',11000 ,'OPEN'     ,'web'    ,'Asia'  ,'2026-06-15'),  -- low    (Jince/Asia)
  ('O-1012','C-004',9000  ,'OPEN'     ,'web'    ,'Europe','2026-06-16');  -- low    (Anil/Europe)

INSERT INTO ORDER_TRIAGE_DB.PUBLIC.CUSTOMERS
  (customer_id, name, tier, region, credit_limit) VALUES
  ('C-001','Acme Corp','enterprise','NA'  ,500000),
  ('C-002','Globex'   ,'smb'       ,'EU'  ,50000 ),
  ('C-003','Initech'  ,'smb'       ,'NA'  ,30000 ),
  ('C-004','Umbrella' ,'enterprise','EU'  ,750000),
  ('C-005','Hooli'    ,'mid'       ,'NA'  ,150000),
  ('C-006','Soylent'  ,'smb'       ,'APAC',20000 );

-- Least-privilege read-only role. Re-grant after CREATE OR REPLACE TABLE (a
-- replaced table is a new object, so prior grants don't carry over).
CREATE ROLE IF NOT EXISTS ORDER_TRIAGE_RO;
GRANT USAGE  ON WAREHOUSE ORDER_TRIAGE_WH        TO ROLE ORDER_TRIAGE_RO;
GRANT USAGE  ON DATABASE  ORDER_TRIAGE_DB        TO ROLE ORDER_TRIAGE_RO;
GRANT USAGE  ON SCHEMA    ORDER_TRIAGE_DB.PUBLIC TO ROLE ORDER_TRIAGE_RO;
GRANT SELECT ON ALL    TABLES IN SCHEMA ORDER_TRIAGE_DB.PUBLIC TO ROLE ORDER_TRIAGE_RO;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ORDER_TRIAGE_DB.PUBLIC TO ROLE ORDER_TRIAGE_RO;

-- Key-pair-only service user (no password). The RSA public key is registered by
-- scripts/snowflake_bootstrap.py via ALTER USER ... SET RSA_PUBLIC_KEY.
CREATE USER IF NOT EXISTS SVC_ORDER_TRIAGE
  DEFAULT_ROLE      = ORDER_TRIAGE_RO
  DEFAULT_WAREHOUSE = ORDER_TRIAGE_WH
  DEFAULT_NAMESPACE = ORDER_TRIAGE_DB.PUBLIC
  COMMENT = 'Read-only key-pair service user for the order-triage agent';
GRANT ROLE ORDER_TRIAGE_RO TO USER SVC_ORDER_TRIAGE;
