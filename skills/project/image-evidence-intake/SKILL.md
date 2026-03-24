---
name: image-evidence-intake
description: Interpret uploaded screenshots or photos as decision evidence for a yes-or-no verdict. Use when the run contains image_inputs, image_ids, or a visual_report, especially for product pages, chat screenshots, tickets, posters, schedules, receipts, bills, or maps.
---

# Image Evidence Intake

Treat uploaded images as evidence, not decoration.

Keep all user-facing output in Simplified Chinese.

## Use This Skill When

- `image_inputs` is present.
- `visual_report` is present.
- The user is clearly asking about what is shown in a screenshot or photo.
- The decision depends on visible details such as price, time, place, tone, policy, schedule, product spec, or availability.

## Do Not Use This Skill When

- There are no uploaded images and no `visual_report`.
- The image adds no decision value beyond the user's text.
- The question is purely abstract and unrelated to what is shown in an attachment.

## Inputs To Check First

Review these inputs before using image evidence:

- `visual_report`
- `image_inputs`
- `classification`
- The user's question, notes, links, and current constraints
- `preflight_tradeoff`

## Core Rule

Prefer `visual_report` as the first-pass summary of the images.

Use image evidence to ground the verdict, but do not pretend to know anything
that is not visible in the frame or explicitly captured in `visual_report`.

## Workflow

1. Identify what kind of image evidence this is.
   Common cases: product page, course page, ticket, event poster, schedule,
   receipt, chat screenshot, map, booking page, or policy screen.

2. Extract only decision-critical facts.
   Prefer 3 to 5 short facts such as:
   - price or fee breakdown,
   - date and time,
   - location,
   - policy or restrictions,
   - availability,
   - product or course scope,
   - emotional tone or boundary signal in chats.

3. Check the confidence of the image evidence itself.
   Mark uncertainty when the image is blurry, cropped, partially visible,
   inconsistent across multiple screenshots, or missing the one detail that
   would actually decide the case.

4. Compare image evidence with the user's text.
   If they align, let the image evidence increase grounding.
   If they conflict, surface the conflict explicitly and lower confidence.

5. Convert image evidence into one useful adjustment.
   Let the image evidence change at least one of these:
   - `why_yes`
   - `why_no`
   - `top_risks`
   - `recommended_next_step`
   - confidence

## Priorities

When image evidence is relevant, prioritize in this order:

1. Clearly visible facts in the image
2. Explicit uncertainties in `visual_report`
3. User text that explains missing context
4. General assumptions

If the image and text disagree, do not silently choose one. Name the conflict.

## Guardrails

- Do not hallucinate hidden text, unseen context, or off-screen details.
- Do not over-read emotional intent from one chat screenshot.
- Do not treat marketing visuals as the same thing as verified policy.
- Do not let one flashy screenshot outweigh stronger confirmed evidence.
- If the image is incomplete, lower confidence before you simplify the story.

## What Good Use Looks Like

- "The screenshot confirms the ticket price and start time, but not the refund rule."
- "The chat tone suggests hesitation, but one cropped screenshot is not enough to assume rejection."
- "The image mostly changes the next step: confirm the uncropped schedule before deciding."

## What Bad Use Looks Like

- "The screenshot definitely proves this will be worth it."
- "This person is clearly angry" based on a tiny chat fragment.
- Treating a poster as proof of logistics, refund policy, or final availability.
- Ignoring visible contradictions between the image and the user's text.

## Success Criteria

This skill worked well if:

- The verdict uses image evidence without sounding overconfident.
- Confirmed image facts are clearly separated from unknowns.
- The final answer gets more concrete, not more dramatic.
- The recommended next step helps the user resolve the one missing visual fact
  that still matters.
