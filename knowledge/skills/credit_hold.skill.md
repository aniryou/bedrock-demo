---
apiName: credit_hold
displayName: "Credit hold"
version: 1
description: >
  Use when a customer may be over their credit limit or the request mentions
  credit, SAP, or holds.
appliesTo:
  objectTypes: [CreditProfile, CustomerProfile]
  linkTypes:   [customerHasCredit]
  actions:     [approveCreditLimit, raiseException]
invokes:       [raiseException]
reads:
  objectTypes: [CreditProfile, CustomerProfile, SalesOrder]
  datasources: [sap]
---
# Credit Hold

Goal: determine whether the customer is on a credit hold before approving new orders.

Steps:
1. Identify the customer (from the order via `ask_orders`, or directly by id/name).
2. Call `sap_credit_check` for that customer to read their SAP credit status and balance.
3. Consult `search_policies` for the credit-hold policy thresholds.
4. If SAP reports `on_hold = true` or the available credit is below the order amount,
   recommend holding the order and `flag_order_for_review` on any OPEN order from them.
5. Summarize: customer, SAP status, available credit, and the recommended action.
