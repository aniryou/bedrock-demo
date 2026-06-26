# Where Know-How Lives

*A primer on distilling business context for agents: the three layers know-how splits across, the feedback loop that keeps them current, and the governance that keeps the whole thing audit-safe.*

## The problem

The ontology captures an organization's concrete core — what exists, how it relates, what is permitted. But most of how an organization actually operates is soft and undocumented: *you do X for Y, except when Z*. This know-how is what makes an agent useful, and what makes it dangerous when it's wrong.

The instinct is to file all of it in a knowledge base and let retrieval sort it out. That simultaneously under-uses the ontology and over-trusts retrieval. The better frame is that a single piece of know-how rarely belongs in one place. "X for Y except when Z" shatters across three layers, and the discipline is knowing which fragment goes where — and pushing each one as far up the stack as it will legitimately go.

## Three layers

The ontology is the board and the legal moves; a skill is a play you run; the knowledge base is the reference library. Each step up the stack trades flexibility for reliability.

**Ontology** — what exists and what is *permitted*, enforced and machine-checkable, always in context. The moment an "except when Z" is deterministic and enforceable, it stops being soft know-how and becomes a rule. "Approve credit above $10M → committee" is an `approval` policy; "never past 90 days" is action validation. Harden whatever you can, because this is the only layer that is audit-grade and cannot be silently skipped.

**Skill** — *how to act* when a task matches: a curated, versioned procedure or unit of judgment, surfaced by its description when the situation arises. This is the home for genuine judgment that doesn't reduce to a rule — how to weigh a borderline committee-override request, what to check and in what order. Because a skill is triggered by the situation, it is deterministically present when that situation occurs.

**Knowledge base** — *what to consult*: raw, high-volume, slowly-consulted material such as the credit-policy document, prior committee decisions, and regulatory text. Retrieved on demand, carrying provenance back to source. It is cheap to add to and makes no promise about *when* it will influence behavior.

The KB will hold ten times what the skills do, and the skills ten times what the ontology enforces — but reliability runs in the opposite direction.

| Layer | What it answers | When it's present | Who changes it | Credit-risk example |
|---|---|---|---|---|
| Ontology | what exists / what's permitted | always — enforced | PR + validation | limit ≤ 90 days; approve > $10M needs committee |
| Skill | how to act on a matching task | when its trigger matches | domain owner, versioned | how to handle a committee-override request |
| Knowledge base | what to consult | only when retrieved | author, light review | the credit-policy doc; past committee rulings |

## Placing a piece of know-how

Ask three questions, in order, and stop at the first yes:

1. Can I state it as a rule a validator or policy engine checks? → **ontology**. Enforce it; don't merely advise it.
2. Is it a procedure or judgment the agent must apply whenever a matching task arises? → **skill**. Curate and version it.
3. Is it large, long-tail, occasionally consulted, or in need of citation? → **knowledge base**. Let it be retrieved.

The order matters because the layers are ranked by reliability, and you want each fragment as high as it honestly goes.

Worked example. Take one sentence of operating policy:

> We extend customer credit, but never past 90 days, require collateral for high-risk markets, flag accounts above 80% utilization, and avoid new credit after a recent default — unless the committee overrides.

It does not belong in one layer. It splits cleanly:

- The 90-day cap, the 80%-utilization flag, and the high-risk-market list are deterministic → **ontology** (action validation against `CreditProfile`; the 80%-utilization threshold is a deterministic check the validation rule references).
- *How* to handle the committee-override case — what to weigh, what to verify — is judgment → a **skill** (`handle_credit_override`).
- The policy document and the precedent rulings that skill leans on → **knowledge base**.

One sentence, three homes. Most real know-how looks like this.

## Skill or knowledge base: the part that trips people up

The deciding axis is **retrieval reliability**. A KB chunk changes behavior only if it happens to be retrieved — fine for "consult if relevant," fragile for "must apply every time." A skill (triggered) and an ontology rule (always in context) are deterministically there when needed.

So the question is not "is this a document or a procedure." It is *how reliably must this know-how fire*. A nuance the agent should weigh occasionally can sit in the KB. A check it must run every time a `Customer`'s credit utilization crosses 80% cannot depend on retrieval luck. **The more reliably something must fire, the further up the stack it belongs.**

## The feedback loop

Documented know-how is a snapshot; the business keeps moving. The richest signal that a layer has gone stale is the exception — the human override, the flagged gap, the exception-request filed against a hard rule. Each one marks the exact point where what you wrote met reality and lost. The usual failure is that this correction happens in a Slack thread or a hallway "no, do it this way," and never becomes data.

So the foundational move is to make *correcting the agent* emit a structured record, keyed by the ontology `apiName`s in play — the entity, the action, and the source artifact that was driving the behavior (a skill version, a KB citation, or a named rule). Same stable-reference discipline as the rest of the system: you can then ask which feedback touched which piece of know-how, and trace any correction forward to the layer it should change.

```yaml
# A feedback record. Capturing one is automatic and changes nothing on its own.
- id: fb_2026_0142
  timestamp: "2026-06-15T09:24:00+08:00"
  signal: override                 # override | gap_flag | exception_request | unused
  subject:                         # the ontology references in play
    objectType: CreditProfile
    action: approveCreditLimit
    property: null
  sourceArtifact: "skill:handle_credit_override@v3"   # what was driving the behavior
  documented: "Recommend decline — customer had a default within 12 months."
  correction: "Officer approved with collateral; cited 18-month clean record since."
  actor: credit_officer            # role apiName
  context: { customerId: CUST-4471, requestedLimitUsd: 12000000 }
  disposition: open                # set by triage: promote | relax | retire | dismiss
```

A working loop has three parts:

- **Signal** — what counts as evidence: overrides, gap-flags, exception frequency.
- **Trigger** — when accumulated evidence becomes a *proposal* to change a layer: "this skill was overridden eight times this month"; "this KB doc was cited forty times and never contradicted"; "this rule drew twelve exception-requests."
- **Gate** — who approves the change, scaled to its blast radius (below).

And it runs both directions. Promotion — soft → curated → enforced — is only half of it. A hard rule that keeps generating exception-requests is not being violated; it is *too rigid*, and the signal says relax it back to an advisory skill. KB articles never retrieved and skills that never fire are retired. It is a control loop, not a ratchet.

| Pattern of evidence | Read | Action |
|---|---|---|
| KB doc cited often, never contradicted | stable, reliable know-how | promote KB → skill (codify) |
| Skill overridden the same way repeatedly | procedure is wrong or incomplete | revise the skill; if the corrected behavior is now deterministic, promote skill → ontology rule |
| Hard rule drawing repeated exception-requests | rule too rigid | relax ontology rule → advisory skill |
| Skill that never fires / KB chunk never retrieved | dead weight | retire |
| Scattered one-off corrections, no pattern | noise, not signal | dismiss; keep watching |

## Governance: capture is cheap, change is not

The asymmetry that keeps this audit-safe: **capturing** a signal is automatic and ungated, because recording an exception changes nothing. **Acting** on a signal is gated, and the gate scales with how much behavior the change governs.

| Change | Layer | Gate |
|---|---|---|
| Add or edit a KB article | knowledge | author + light review; provenance required |
| Add or revise a skill | skill | domain-owner review; versioned (`@v+1`) |
| Add, relax, or change an enforced rule or policy | ontology | PR + `validate.py` + domain approver; audit-log entry |

The non-negotiable: the agent **surfaces candidates with evidence; it never silently rewrites its own rules.** A self-modifying enforced layer destroys the audit trail — exactly what a credit-risk system cannot afford. Soft layers are allowed to adapt quickly, because being wrong there is recoverable and visible. The enforced layer changes slowly and on purpose. Nothing changes itself.

## The thread that ties it together

One discipline runs through all of it: everything references the ontology by `apiName`. Skills and KB articles speak in entity and action names ("for a `Customer` whose credit utilization exceeds 0.8…"); KB chunks are tagged by the entities they concern; feedback records are keyed the same way.

Get that one convention right and the rest is bookkeeping. The ontology stays the enforced spine. Skills and knowledge carry everything softer. The feedback loop moves know-how up the stack as it hardens and back down as it loosens — slowly where it counts, and never on its own.
