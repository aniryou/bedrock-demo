---
apiName: high_value_review
displayName: "High-value review"
version: 1
description: >
  Use when an order is large relative to the customer's credit limit, or any
  partner order at/above $100k.
appliesTo:
  objectTypes: [SalesOrder, CreditProfile, CustomerProfile]
  linkTypes:   [salesOrderPrioritisedByProfile]
  actions:     [raiseException, approveCreditLimit]
invokes:       [raiseException]
reads:
  objectTypes: [SalesOrder, CreditProfile, CustomerProfile]
  datasources: [sap]
---
# High-Value Review

Goal: decide whether a high-exposure OPEN order should be flagged for human review.

Steps:
1. Look up the order and customer with `ask_orders` (amount, status, tier, channel, credit limit).
2. Score the order with `score_order`. Only continue if the risk is **high**.
3. For partner-channel orders at or above $100,000, also run `sap_credit_check` on the
   customer to confirm there is no outstanding credit hold in SAP.
4. If risk is high (and SAP shows a hold or no offsetting credit), call
   `flag_order_for_review` with a one-line reason naming the exposure ratio and channel.
5. Never claim an order was flagged unless `flag_order_for_review` confirmed it.
