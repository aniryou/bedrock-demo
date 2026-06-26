---
apiName: using_the_knowledge_layer
displayName: "Using the knowledge layer"
version: 1
description: >
  Foundational doctrine: what the ontology, skills, and knowledge base are and how to
  use them together. Pre-loaded into every agent's prompt.
preload: true
---
# Using the knowledge layer

This is foundational guidance for every agent built on this knowledge layer. The
ontology, skills, and knowledge base are the enterprise's source of truth — consume
them; do not restate or redefine them in your own instructions.

## The three layers (ranked by reliability)

- **Ontology** — what exists and what is *permitted*: object types, the actions that may
  be taken on them, and the datasource that is each entity's system of record. Always
  authoritative. It is the *design* model, not your runtime schema.
- **Skills** — *how to act* when a task matches: curated, versioned playbooks. When a
  request matches one, read it before acting.
- **Knowledge base** — *what to consult*: policies and reference material, retrieved on
  demand and cited.

The higher the layer, the more reliably it must hold. Push every decision to the highest
layer that legitimately covers it.

## How to work a request

1. For a simple lookup, use your tools directly.
2. For a governed task (credit, disputes, exposure, and the like), find the skill that
   governs it first: match the skills catalog in your prompt, or call
   `describe_entity(apiName)` to see which skills, actions, and KB docs govern an ontology
   entity (e.g. CreditProfile, SalesOrder, Dispute). Then `load_skill(name)` and follow
   its steps.
3. Ground any policy decision in `search_policies` (the knowledge base) and cite the
   policy you used.

## Discipline

- Ontology names are the *design* model. They are not the field names your data tools
  query, and they are never tool arguments — use them to decide *which* skill or action
  applies, then act through your tools.
- Do not invent skills, entities, or policies. If the knowledge layer does not cover a
  case, say so rather than improvising a rule.
