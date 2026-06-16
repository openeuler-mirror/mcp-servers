---
name: patch-similarity-evaluator
description: Evaluate AI-generated backport patches against manual reference patches using layered Git and structural evidence. Use when assessing patch correctness or semantic equivalence from ai_backport_eval Excel workbooks, comparing manual and AI patches, triaging decision=mystique_patch cases, or preparing uncertain patch pairs for LLM review.
---

# Patch Similarity Evaluator

Evaluate similarity first, then assess semantic equivalence. Never claim that similarity alone proves correctness.

## Workflow

1. Identify the common target baseline and reference patch.
   - Prefer patches produced from the same `case_baseline`.
   - If patches use different baselines, apply both independently to clean worktrees at the same target baseline before comparing resulting trees or blobs.
   - Do not compare whole trees from unrelated parents.
2. Run the deterministic evaluator:

```bash
python3 scripts/evaluate_patch_similarity.py INPUT.xlsx --output-dir OUTPUT_DIR
```

3. Interpret evidence in this order:
   - `tree_match_manual=true`: strongest available result-equivalence evidence when both results share a baseline.
   - `patch_id_match=true`: strong patch-equivalence evidence; ignores whitespace and line numbers.
   - Exact changed-file set plus high structural score: likely similar, but still inspect semantic differences.
   - Different files, missing changed regions, extra behavior, or low structural score: treat as divergent.
4. Read `llm_review.jsonl` only for cases whose verdict requires semantic review. Follow [references/judgement.md](references/judgement.md).
5. Validate likely-equivalent patches with available build, focused tests, static checks, and security invariants.

## Decision Rules

- Report `result_tree_match` only when the workbook explicitly records a valid same-baseline comparison.
- Report `patch_id_equivalent` when stable patch IDs match.
- Report `likely_equivalent_needs_validation` only when changed-file sets match and structural similarity is high.
- Report `semantic_review_required` for mechanically ambiguous cases.
- Report `divergent` when changed-file coverage or changed behavior materially differs.
- Report `insufficient_data` when either patch is missing or malformed.

Do not turn `likely_equivalent_needs_validation` into `correct`. A manual patch is a reference implementation, not infallible ground truth, and a semantically correct AI backport may differ structurally.
