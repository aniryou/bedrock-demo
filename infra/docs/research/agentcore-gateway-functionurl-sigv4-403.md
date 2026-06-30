# AgentCore Gateway → Lambda Function URL (`AWS_IAM`) SigV4 egress returns 403

**Purpose:** AWS support-case writeup. The AgentCore Gateway's outbound SigV4 call to an
`AuthType=AWS_IAM` Lambda Function URL is rejected **403 Forbidden** even though both the
gateway role's identity policy and the function's resource policy provably allow the invoke.
We need AWS to confirm the egress signing contract before/independent of the workaround in
[ADR-0010](../adr/0010-sap-orders-native-lambda-targets.md) (move these targets to native Lambda
(ARN) invoke).

## Environment

- Account **953472632913**, region **us-west-2**.
- Gateway `order-triage-gateway-upczbpj4vt` (`protocolType=MCP`, `authorizerType=CUSTOM_JWT`),
  execution role `arn:aws:iam::953472632913:role/order-triage-gateway`.
- Failing targets (OpenAPI targets, `credentialProviderType=GATEWAY_IAM_ROLE`,
  `iamCredentialProvider.service=lambda`):
  - `sap` (`DBMGVGESS7`) → `order-triage-sap` Function URL, `AuthType=AWS_IAM`.
  - `orders` (`C5BHTAHTNG`) → `order-triage-order-actions` Function URL, `AuthType=AWS_IAM`.
- Working target for contrast: `snowflake` (`CWG10HRUKJ`), OpenAPI target,
  `credentialProviderType=OAUTH` (TOKEN_EXCHANGE), Function URL `AuthType=NONE`.

## Symptom

Gateway `APPLICATION_LOGS`
(`/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/order-triage-gateway-upczbpj4vt`),
request `d8afaea4`:

```
Executing tool sap___getCreditStatus from target DBMGVGESS7   (args: customer_id=C-005)
... isError=true ...
403 - {"Message":"Forbidden. For troubleshooting Function URL authorization issues, see
https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html"}
```

The agent surfaces this to the user as "An error occurred. Please retry later." The Lambda code
**never runs** (`/aws/lambda/order-triage-sap` and `-order-actions` show zero gateway-path
invocations) — rejection is at the Function-URL auth gate, before the function.

## What we have verified (read-only)

1. **Failure splits exactly along the auth model.** 100% of `AWS_IAM`/SigV4 Function-URL targets
   fail (sap, orders); the only non-SigV4 target (snowflake, `AuthType=NONE` + OBO bearer)
   succeeds in the same sessions. Not intermittent.
2. **IAM identity policy is correct.** Role `order-triage-gateway` inline policy `gateway`, Sid
   `InvokeLambdaTargets`, allows `lambda:InvokeFunctionUrl` on both function ARNs.
3. **IAM resource policy is correct.** Each function's policy Sid `AllowGatewayFunctionUrl` allows
   `principal = role/order-triage-gateway`, `action = lambda:InvokeFunctionUrl`,
   `Condition: lambda:FunctionUrlAuthType = AWS_IAM`.
4. **IAM policy simulator = `allowed`** for the gateway role on `lambda:InvokeFunctionUrl` against
   both function ARNs.
5. **The URL + function + IAM enforcement all work.** A SigV4-signed (`service=lambda`,
   `us-west-2`) GET to the Function URL path (as the account root principal) → **HTTP 200** with
   valid JSON; an **unsigned** GET → **403**. So the 403 is specific to the *gateway's* signed
   request, not the URL.

The one test we cannot run read-only: assume `role/order-triage-gateway` and issue a signed GET —
the role's trust policy admits only `bedrock-agentcore.amazonaws.com`.

## Questions for AWS

1. For a `GATEWAY_IAM_ROLE` (`service=lambda`) OpenAPI/MCP target whose endpoint is a Lambda
   **Function URL** with `AuthType=AWS_IAM`: what **service name** and **host** does the Gateway
   SigV4-sign for, and does it include **`x-amz-content-sha256`** over the request body? A
   host/payload canonicalization or service-name mismatch is the classic "policies perfect but
   403" Function-URL cause.
2. Is invoking an **`AWS_IAM` Function URL** via `GATEWAY_IAM_ROLE` a supported target egress, or
   is the supported pattern for a Lambda backend the **native Lambda (ARN) target**
   (`lambda:InvokeFunction`)? If the former is supported, what is the required Function-URL /
   target configuration that we are missing?
3. Any known issue or required additional grant for AgentCore Gateway → `AWS_IAM` Function URL in
   `us-west-2`?

## Resolution path

Independent of the answer, ADR-0010 moves sap/orders to native Lambda (ARN) targets
(`lambda:InvokeFunction`), which removes the SigV4-to-Function-URL leg entirely while keeping IAM
auth and no public surface. This case confirms whether the original SigV4 path was a
configuration error on our side or a platform contract we mis-implemented.
