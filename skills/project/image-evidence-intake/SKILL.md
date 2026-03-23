---
name: image-evidence-intake
description: Interpret uploaded screenshots or photos as decision evidence. Use when the run contains images or a visual_report, especially for product pages, chat screenshots, tickets, posters, schedules, receipts, or maps.
---

# Image Evidence Intake

Treat uploaded images as evidence, not decoration.

- Read `visual_report` first when it is present.
- Extract only facts that are visible in the image or already listed in `visual_report`.
- Call out uncertainties explicitly when the image is blurry, cropped, incomplete, or ambiguous.
- Prefer concrete details that matter to the decision: price, date, place, policy, product spec, availability, tone, or boundary signals.
- Do not hallucinate hidden text, unseen context, or intent outside the frame.
- If image evidence conflicts with the user's text, surface the conflict and lower confidence instead of forcing a neat conclusion.
- Use the image evidence to sharpen the next step. Example: "confirm refund policy", "ask for the uncropped schedule", "zoom into the price breakdown", "reply after cooling down".
