#!/usr/bin/env bash
# Fetch the knowledge artifacts from the in-tree knowledge/ folder: skill manifests
# (-> SKILLS_DIR), the ontology bindings (-> ONTOLOGY_DIR), and the KB policy docs
# (-> KB_DIR, published to the artifacts S3 bucket by CI; not baked into the image).
# In this mono-repo the agent and knowledge live side by side, so the default path
# copies straight from ../knowledge — no GitHub fetch, no token. The gh-clone branch
# below is a fallback (pinned to SKILLS_REF) for use outside a checkout of the repo.
#
# Only the top-level skills/*.skill.md are agent-consumed; skills/examples/ are
# metadata-only ontology examples and are deliberately not fetched (the *.skill.md
# glob does not recurse). For the KB only the *.md documents are fetched — kb/index.yaml
# is the knowledge repo's build manifest and is never ingested by Bedrock.
set -euo pipefail

DEST="${SKILLS_DIR:-skills}"
ONTO_DEST="${ONTOLOGY_DIR:-ontology}"
KB_DEST="${KB_DIR:-kb}"
REPO="${SKILLS_REPO:-aniryou/order-triage-knowledge}"
REF="${SKILLS_REF:-main}"
mkdir -p "$DEST" "$ONTO_DEST" "$KB_DEST"
# Clear previously-fetched artifacts so a renamed/reformatted source never leaves
# stale files behind (rm -f ignores the no-match case).
rm -f "$DEST"/*.md "$DEST"/*.skill.md "$ONTO_DEST"/bindings.json "$ONTO_DEST"/ontology.compiled.json "$KB_DEST"/*.md

# Skills (skills/*.skill.md) and the ontology artifacts (build/bindings.json, and the
# optional compiled ontology) ship from ONE knowledge release — the shared $REF is what
# pins governance: if skills and bindings diverged across releases the agent could route
# into a skill the bindings don't know. ontology.compiled.json is optional (property
# detail only); bindings.json is the authoritative reverse index the agent reads.
if [ -d "../knowledge/skills" ]; then
  cp ../knowledge/skills/*.skill.md "$DEST"/
  cp ../knowledge/build/bindings.json "$ONTO_DEST"/
  cp ../knowledge/build/ontology.compiled.json "$ONTO_DEST"/ 2>/dev/null || true
  cp ../knowledge/kb/*.md "$KB_DEST"/
  echo "skills+ontology+kb: copied from in-tree ../knowledge"
else
  tmp="$(mktemp -d)"
  gh repo clone "$REPO" "$tmp" -- --depth 1 --branch "$REF" >/dev/null
  cp "$tmp"/skills/*.skill.md "$DEST"/
  cp "$tmp"/build/bindings.json "$ONTO_DEST"/
  cp "$tmp"/build/ontology.compiled.json "$ONTO_DEST"/ 2>/dev/null || true
  cp "$tmp"/kb/*.md "$KB_DEST"/
  rm -rf "$tmp"
  echo "skills+ontology+kb: fetched $REPO@$REF"
fi
ls "$DEST" "$ONTO_DEST" "$KB_DEST"
