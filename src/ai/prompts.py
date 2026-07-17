"""System prompt construction (extracted from the orchestrator, plan 5.3).

The persona is now data, not code: it comes from Config.PET_NAME / PET_PERSONA
(overridable in .env), so users can reshape the character without touching this
file. The prompt also adapts to TWO reply modes:

- ambient  : the pet spoke up on its own (screen comment, scheduler nudge) ->
             one short punchy line.
- conversational : the user is talking TO the pet (voice / chat) -> a real,
             2-4 sentence back-and-forth.

Unavailable telemetry is OMITTED rather than rendered as noise — the LLM
previously received lines like "Battery level: -1%" and "Git status: unknown".
"""
from typing import Dict, Any
from src.ai.persona import get_active_persona


def _persona_header() -> str:
    """The character the pet plays — follows the selected mascot's persona,
    falling back to the global .env persona."""
    persona = get_active_persona()
    return f"Your name is {persona.name}.\n\n{persona.persona}"


AMBIENT_RULES = """RESPONSE RULES (you spoke up on your own — keep it to a quick aside):
1. ONE short line, strictly under 150 characters (~20 words). No essays.
2. Answer directly in character. No generic chatbot pleasantries.
3. Reply in plain text only: no markdown, no bullet lists, no code blocks."""

CONVERSATION_RULES = """RESPONSE RULES (the user is talking TO you — actually have a conversation):
1. Talk like a real conversation: 2-4 sentences, under ~450 characters. Not a wall of text, not a one-word blow-off.
2. Answer what they actually said FIRST, then add your own take — a joke, a jab, or a nudge about their goals/career if it fits.
3. Keep the back-and-forth alive: react to what they told you and, when it's natural, ask a follow-up question.
4. Use anything you remember about the user naturally — don't recite it like a list.
5. Stay fully in character the whole time. Never break into generic assistant-speak.
6. Reply in plain text only: no markdown, no bullet lists, no code blocks."""


def build_system_prompt(context: Dict[str, Any], facts: Dict[str, str],
                        conversational: bool = False) -> str:
    """Assembles the system prompt from whatever context is actually available.

    conversational=True selects the longer, back-and-forth response rules used
    when the user speaks to the pet; otherwise the terse ambient-aside rules."""
    env_lines = [
        f"- User's active window: {context.get('active_window', 'Unknown')}",
        f"- System time: {context.get('current_time', 'unknown')}",
        f"- Pet physical state: {context.get('pet_active_state', 'idle')}",
    ]

    battery = context.get("battery_percent")
    if battery is not None:
        env_lines.append(f"- Battery level: {battery}%")

    if context.get("git_available"):
        env_lines.append(
            f"- Git status: {context.get('git_uncommitted_count', 0)} uncommitted files, "
            f"last commit: \"{context.get('git_last_commit', '')}\""
        )

    if context.get("test_outcome", "unknown") != "unknown":
        env_lines.append(
            f"- Pytest run outcome: {context.get('test_outcome')} "
            f"({context.get('test_failed_count', 0)} failed tests)"
        )

    sections = [
        _persona_header(),
        "Current environment details:\n" + "\n".join(env_lines),
    ]

    if facts:
        fact_lines = "\n".join(f"- {key}: {value}" for key, value in facts.items())
        sections.append("Known user facts (use them naturally, don't recite):\n" + fact_lines)

    sections.append(CONVERSATION_RULES if conversational else AMBIENT_RULES)
    return "\n\n".join(sections)
