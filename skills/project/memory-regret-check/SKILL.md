---
name: memory-regret-check
description: Use stored preference and regret memory to detect repeated decision traps without overfitting. Use when memory_snapshot is present and the current case may rhyme with a known pattern, especially before finalizing a structured verdict.
compatibility: Designed for the do-or-not project with classification, preflight_tradeoff, memory_snapshot, and structured RunVerdict output.
---

# Memory Regret Check

## Purpose

Use this skill to turn feedback memory into a useful decision aid instead of a
vague background hint.

The goal is to answer one question:

"Is this case repeating a known pattern, or does it only look similar on the
surface?"

Keep all user-facing output in Simplified Chinese.

## Use This Skill When

- `memory_snapshot` is present.
- You are about to finalize a verdict.
- The current question resembles a recurring pattern in spending, travel,
  social, or work-learning decisions.
- The agent has enough context to compare the current case against past memory.

## Do Not Use This Skill When

- Memory is empty or generic.
- The current case has no meaningful overlap with stored patterns.
- Memory would distract from stronger present-tense evidence.

## Inputs To Check First

Review these inputs before using memory:

- `classification`
- `preflight_tradeoff`
- `memory_snapshot.profile_markdown`
- `memory_snapshot.regret_markdown`
- `visual_report` when present
- The user's current constraints such as budget, deadline, links, and notes

## Workflow

1. Identify the closest relevant memory signals.
   Use at most 2 preference patterns and at most 2 regret patterns.

2. Compare, do not copy.
   Decide whether the current case is:
   - truly similar,
   - partly similar, or
   - only superficially similar.

3. Name the likely repeat-risk internally.
   Example: buying for mood relief, starting too big, acting with thin facts,
   waiting too long, or over-researching.

4. Convert memory into one concrete adjustment.
   Put that adjustment into `top_risks`, `recommended_next_step`, or the main
   reasoning.

5. Keep memory proportional.
   Memory can lower or raise confidence, but it should not override stronger
   current facts.

6. Prefer one clear lesson over many weak echoes.
   If several patterns partly match, choose the single repeat-risk that would
   most improve the user's next step.

## Priority Order

When memory competes with other evidence, prefer this order:

1. Current verified facts
2. Image or link evidence grounded in the current case
3. Current user constraints
4. `preflight_tradeoff`
5. Relevant memory

If memory still matters after that comparison, use it to refine the verdict,
not to replace the present tense evidence.

## Guardrails

- Never force memory into the answer if relevance is weak.
- Never assume same category means same situation.
- Do not overfit to a single past feedback item.
- Prioritize current constraints over old habits when they conflict.
- Do not dump the memory snapshot back to the user verbatim.
- Do not revive stale memory just to sound personalized.
- Do not re-run local scoring tools only because memory exists.

## What Good Use Looks Like

Good use of memory sounds like this:

- "This looks similar to your past pattern of buying for immediate excitement."
- "This is different from your past regret pattern because the budget and usage
  frequency are clearer this time."
- "The memory mainly changes confidence and next step, not the core verdict."
- "This resembles your old pattern of starting too big, so the safest next step
  is to shrink scope before committing."

## What Bad Use Looks Like

- "You always regret this kind of thing."
- "Past memory says no, so the answer is no."
- Repeating every stored preference regardless of relevance.
- Letting memory drown out stronger new evidence from the current case.
- Treating memory as a substitute for reading the current screenshots, links,
  or constraints.

## Escalation Rule

If memory and current evidence point in different directions, prefer this order:

1. Current verified facts
2. Current user constraints
3. Preflight tradeoff
4. Relevant memory

If the conflict remains real, keep the verdict but lower confidence and make the
next step more cautious.

If the conflict is weak or fuzzy, drop the memory instead of forcing a dramatic
warning.

## Success Criteria

This skill worked well if:

- The final verdict clearly reflects memory without sounding trapped by it.
- The answer names one realistic repeat-risk.
- The recommended next step helps the user avoid the old mistake in a concrete
  way.
- The result feels more personal, but not overfit.
