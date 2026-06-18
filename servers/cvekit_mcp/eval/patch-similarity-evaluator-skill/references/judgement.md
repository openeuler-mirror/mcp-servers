# Semantic Judgement Guide

Use this guide only after deterministic evidence fails to establish a strong result.

## Review Questions

1. What vulnerability or defect does the source/manual patch fix?
2. Does the AI patch enforce the same security and functional invariant on the target baseline?
3. Does the AI patch cover every path handled by the manual patch?
4. Does it introduce extra behavior, unrelated cleanup, API changes, or regressions?
5. Are differences justified by target-version code structure, renamed symbols, moved files, or already-present behavior?
6. Are error paths, locking, lifetime, bounds, integer behavior, and cleanup semantics preserved?
7. Does low `manual_change_coverage` reveal behavior omitted by the AI patch?
8. Does low `ai_change_precision` or `extra_ai_files` reveal unrelated or risky extra behavior?

## Context Depth During Semantic Review

Use this section only after a case has already been selected for semantic review. Do not use it to decide whether a case enters semantic review.

Start with patch-only review:

- Compare touched files, changed lines, hunk labels, added/deleted behavior, and mechanical evidence.
- Check whether low `manual_change_coverage` means the AI patch omitted manual behavior.
- Check whether low `ai_change_precision` or `extra_ai_files` means the AI patch introduced unrelated behavior.
- When added code looks similar, verify equivalent execution conditions, ordering, path coverage, and any old behavior it replaces.
- If the manual patch and AI patch alone clearly show equivalent behavior, missing behavior, or extra behavior, finish the judgement without inspecting repositories.

Escalate to `target_repo@case_baseline` only when patch-only evidence cannot answer the semantic question:

- The same files are touched, but changed lines or hunk labels differ materially.
- Coverage and precision disagree, especially when AI covers much of the manual patch but adds extra behavior.
- The AI patch adds new logic but may have missed old logic that the manual patch removed or replaced.
- The target version may already contain part of the manual fix.
- Paths, symbols, functions, or macros may have moved or been renamed.
- Correctness depends on surrounding control flow, locking, lifetime, cleanup, bounds, or error paths.

When repository context is needed, use `target_repo` checked out at `case_baseline` as the target baseline. Apply the manual patch and AI patch independently to clean worktrees, then compare the resulting changed files, function context, and final diffs.

## Required Evidence

Use the manual patch and AI patch first. Use common baseline context and changed functions only when the escalation rules above require it. Inspect nearby target code when patch hunks differ. Use cvekit's similar-symbol or similar-block techniques when paths or symbols moved.

Do not infer equivalence merely from:

- Similar commit messages or identifiers
- Both patches applying cleanly
- Similar diff size
- Matching file names without matching behavior
- An LLM's unsupported assertion

## Output Schema

Return one JSON object per case:

```json
{
  "source_commit": "...",
  "semantic_verdict": "equivalent|partially_equivalent|not_equivalent|insufficient_context",
  "confidence": 0.0,
  "fixed_invariant": "...",
  "missing_or_extra_behavior": ["..."],
  "evidence": ["..."],
  "required_validation": ["..."]
}
```

Keep JSON keys and enum values in English, including `semantic_verdict`. All natural-language field values must be written in Simplified Chinese:

- `fixed_invariant`
- `missing_or_extra_behavior`
- `evidence`
- `required_validation`

When writing `semantic_judgement.md`, use Chinese headings and Chinese explanatory paragraphs. Keep code symbols, file paths, commit IDs, metric names, and enum values unchanged. Render validation items in Chinese, for example under `建议验证` or `required_validation`.

Use `equivalent` only when the same invariant is enforced across all relevant paths. Always list concrete validation steps in Chinese.
