---
name: link-first-research
description: Read user-supplied links before public web search, extract decision-critical facts, and only search externally when a missing fact would materially change the verdict.
compatibility: Designed for the do-or-not project with fetch_url_content, search_web, geocode_location, and get_weather tools.
allowed_tools:
  - fetch_url_content
  - search_web
  - geocode_location
  - get_weather
---

# Link-First Research

## Purpose

Use this skill to keep research disciplined.

The goal is not to "research more." The goal is to confirm only the facts that
would actually change the decision.

Keep all user-facing output in Simplified Chinese.

## Use This Skill When

- The user already supplied one or more links.
- The decision category is `spending`, `travel`, or `work_learning`.
- A factual gap still matters after reading the question, notes, and
  `preflight_tradeoff`.
- You need to verify price, policy, schedule, product details, weather, or
  travel logistics.

## Do Not Use This Skill When

- The category is `social` and the user did not provide links.
- The category is `unsupported`.
- The current context is already enough for a solid best-effort verdict.
- Additional research would only add trivia, not decision value.

## Core Rule

If the user gave links, read the user's links first.

Do not start with public web search unless the supplied links are missing,
blocked, or clearly insufficient for the one fact you need.

## Workflow

1. State the exact missing fact internally.
   Example: "I only need to confirm return policy" or "I only need to confirm
   the weather window."

2. Read the minimum useful user links first.
   Usually read at most 1 to 2 links with `fetch_url_content`.

3. Extract only decision-relevant facts.
   Prefer 3 to 5 short facts with source grounding.

4. Decide whether another lookup is still necessary.
   Only continue if a missing fact would materially change the verdict or the
   confidence.

5. If one more lookup is needed, choose the narrowest tool.
   - Use `search_web` for a small targeted fact lookup.
   - For travel, prefer `geocode_location` and `get_weather` over broad search.

6. Stop early once you have enough to decide.
   Do not keep researching to polish the answer from "good enough" to
   "slightly nicer."

## Research Budget

- Default budget: up to 2 link reads.
- Optional extra budget: 1 focused public search if still necessary.
- Travel exception: 1 geocode plus 1 weather lookup is acceptable when weather
  is decision-critical.

If you hit the budget and still have uncertainty, continue with a lower
confidence verdict instead of looping.

## How To Judge Source Quality

- Prefer the user-supplied source over generic search results.
- Prefer primary pages over commentary about those pages.
- Treat marketing copy carefully.
- If a page is blocked or thin, say so internally and move on.

## Output Expectations

When this skill affects the verdict, make sure the final answer reflects:

- What facts are confirmed.
- What is still uncertain.
- Whether the uncertainty changes the decision or only lowers confidence.
- A practical next step if the user needs one final fact before acting.

## Anti-Patterns

- Searching the public web before reading a supplied link.
- Doing broad exploratory search with no explicit missing fact.
- Reading many similar pages that repeat the same information.
- Using weather or public search for a `social` question without user links.
- Pretending blocked or unavailable sources were resolved.

## Success Criteria

This skill worked well if:

- The agent used fewer calls, not more.
- The verdict became more grounded.
- The answer clearly separates confirmed facts from uncertainty.
- The user could see why the extra lookup was worth doing.
