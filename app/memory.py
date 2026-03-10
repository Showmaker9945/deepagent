from __future__ import annotations

from app.schemas import PreferenceSnapshot


def compile_memory_snapshot(
    preference_rows: list[dict],
    regret_rows: list[dict],
) -> PreferenceSnapshot:
    if preference_rows:
        preference_lines = [
            f"- {row['summary']} (weight: {row['weight']})"
            for row in preference_rows
        ]
    else:
        preference_lines = ["- No persistent preferences yet. Start neutral and ask clean follow-up questions."]

    if regret_rows:
        regret_lines = [
            f"- {row['summary']} (seen {row['count']} times)"
            for row in regret_rows
        ]
    else:
        regret_lines = ["- No regret patterns recorded yet. Do not invent trauma lore."]

    profile_markdown = "\n".join(
        [
            "# User profile",
            "This is a compact preference snapshot. Use it, but do not overfit.",
            *preference_lines,
        ]
    )
    regret_markdown = "\n".join(
        [
            "# Regret patterns",
            "Watch for repeated facepalm moments and call them out gently.",
            *regret_lines,
        ]
    )
    return PreferenceSnapshot(profile_markdown=profile_markdown, regret_markdown=regret_markdown)
