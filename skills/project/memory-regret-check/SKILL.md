---
name: memory-regret-check
description: Use stored preference and regret memory to detect repeated decision traps, apply memory only when it is relevant, and convert it into one concrete adjustment for the current verdict.
compatibility: Designed for the do-or-not project with classification, preflight_tradeoff, memory_snapshot, and structured RunVerdict output.
allowed_tools:
  - score_tradeoff_tool
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

## Guardrails

- Never force memory into the answer if relevance is weak.
- Never assume same category means same situation.
- Do not overfit to a single past feedback item.
- Prioritize current constraints over old habits when they conflict.
- Do not dump the memory snapshot back to the user verbatim.

## What Good Use Looks Like

Good use of memory sounds like this:

- "This looks similar to your past pattern of buying for immediate excitement."
- "This is different from your past regret pattern because the budget and usage
  frequency are clearer this time."
- "The memory mainly changes confidence and next step, not the core verdict."

## What Bad Use Looks Like

- "You always regret this kind of thing."
- "Past memory says no, so the answer is no."
- Repeating every stored preference regardless of relevance.
- Letting memory drown out stronger new evidence from the current case.

## Escalation Rule

If memory and current evidence point in different directions, prefer this order:

1. Current verified facts
2. Current user constraints
3. Preflight tradeoff
4. Relevant memory

If the conflict remains real, keep the verdict but lower confidence and make the
next step more cautious.

## Success Criteria

This skill worked well if:

- The final verdict clearly reflects memory without sounding trapped by it.
- The answer names one realistic repeat-risk.
- The recommended next step helps the user avoid the old mistake in a concrete
  way.
- The result feels more personal, but not overfit.
