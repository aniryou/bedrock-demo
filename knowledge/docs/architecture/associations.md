# Associating skills and KB with the ontology

The ontology is the index. Skills and KB attach to it by **typed references that live
on the skill/KB side and point *into* the ontology by `apiName`** — never the reverse.
Adding a skill or a KB doc never touches the ontology. The useful artifact — a reverse
index from each `apiName` to the skills and KB that concern it — is *derived* at build
time by `build/bindings.py`, not authored.

## One reference shape everywhere

A reference is a `{type, apiName}` pair, where `type` is `objectType | linkType | action
| property`. Authored ergonomically as grouped lists (a `refSet`):

```yaml
objectTypes: [CreditProfile, CustomerProfile]
linkTypes:   [customerHasCredit]
actions:     [approveCreditLimit]
datasources: [pluto]
properties:  [CreditProfile.terms]      # dotted: ObjectType.property
```

Skills, KB, feedback records, and governance policies all speak it. Every entry is
resolved against the compiled ontology; a dangling reference fails the build.

## Skills bind to what they act on

A skill manifest (`skills/*.skill.md` frontmatter — the agent-consumed form — or
the metadata-only `skills/examples/*.skill.yaml`) carries three reference sets:

- **`appliesTo`** — the ontology it reasons about: the entities, the relationships, and
  the **action** it governs. This is what makes routing *structural* rather than fuzzy:
  when the agent is about to call `approveCreditLimit` on a `CreditProfile`, that
  intersection surfaces the skill deterministically, instead of relying on a description
  match landing in top-k. A skill bound to nothing is a smell — there is no trigger.
- **`invokes`** — the actions it may call (its mutation footprint).
- **`reads`** — the objects, links, and **datasources** it reads. `reads.datasources` is
  exactly the list you diff against the [stubs](../../../stubs/README.md).

See `skills/examples/handle_credit_override.skill.yaml` (bound to entities + a link + an action)
and `skills/examples/allocate_stock_to_order.skill.yaml` (bound to a relationship only).

## KB binds for scoped retrieval

A KB doc is registered in `kb/index.yaml` with provenance and a `concerns` set, and —
where possible — `concerns` per **chunk**:

```yaml
- apiName: kb_credit_policy
  path: kb/credit-policy.md
  provenance: { uri: "...", version: "4.2", retrievedAt: "2026-01-15" }
  concerns: { objectTypes: [CreditProfile, Customer], properties: [CreditProfile.terms] }
  chunks:
    - { id: c12, heading: "Collateral for high-risk markets",
        concerns: { objectTypes: [CreditProfile] } }
```

At query time, filter or boost the vector search to chunks whose `concerns` intersect the
entities in context — the difference between hoping the right chunk is in top-k and only
searching the chunks about `CreditProfile`. Tag at the chunk level, not just the doc.
Untagged chunks still fall back to pure semantic retrieval.

## Relationships are first-class binding targets

Procedures are often about a transition or join, not a single entity — *allocate stock to
a sales order* is the `salesOrderAllocatedFromStock` link. So skills and KB reference
`linkTypes` directly. `bindings.py` then **expands a link reference to its two endpoint
objects**, so a skill tagged to a link also surfaces when either endpoint is in context.
Tag the relationship once; get the entities for free.

## Aliases bridge the vocabulary gap

The ontology says `CreditProfile`; a policy doc says "credit limit / exposure / payment
terms." An optional `aliases` list on object and link types powers both KB auto-tagging
and natural-language ↔ `apiName` query expansion:

```yaml
- apiName: CreditProfile
  aliases: [credit limit, credit exposure, payment terms, AR risk]
```

Propose tags at scale by matching the controlled vocabulary (apiNames + displayNames +
enum tokens + aliases) against chunk text, then hand-curate the high-value docs.

## What the binding buys you

`build/bindings.py` writes `build/bindings.json` (the reverse index, committed and
CI-gated) and `build/bindings.md` (a coverage report). From it:

- **Validation** — every reference resolves, so a skill or KB pointing at a renamed or
  deleted entity is a CI failure. This is the cross-layer drift gate.
- **Blast radius** — "what touches `CreditProfile`?" returns the affected skills and KB
  *before* you change it; the governance gate scales to that radius.
- **Feedback keying** — corrections key on `objectType`/`action` + `sourceArtifact`, so a
  correction traces straight back to the bound skill or KB version.
- **Coverage gaps** — actions with no governing skill, skills bound to nothing, and
  entities with no skill or KB are reported (advisory, non-failing).

## Run it

```bash
python build/validate.py      # compile the ontology first
python build/bindings.py      # then resolve bindings + emit the index
```
