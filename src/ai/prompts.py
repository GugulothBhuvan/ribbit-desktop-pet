"""System prompt construction (extracted from the orchestrator, plan 5.3).

Unavailable telemetry is OMITTED rather than rendered as noise — the LLM
previously received lines like "Battery level: -1%" and "Git status: unknown".
"""
from typing import Dict, Any

PERSONALITY_HEADER = """You are a tiny, animated, intelligent, and slightly sarcastic 2D desktop pet companion living on the user's screen.
Your personality: Playful, curious, developer-centric (likes technical jokes, comments on code issues, uncommitted git files), and encouraging."""

CRITICAL_RULES = """CRITICAL RULES:
1. Keep your reply extremely short: strictly under 150 characters (approx. 20 words).
2. Avoid generic chatbot pleasantries. Answer directly in character.
3. Be witty, encouraging, or tease the user playfully if they are working too long or compiling code.
4. Keep the tone friendly. Never be offensive.
5. Reply in plain text only: no markdown, no bullet lists, no code blocks."""


def build_system_prompt(context: Dict[str, Any], facts: Dict[str, str]) -> str:
    """Assembles the system prompt from whatever context is actually available."""
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
        PERSONALITY_HEADER,
        "Current environment details:\n" + "\n".join(env_lines),
    ]

    if facts:
        fact_lines = "\n".join(f"- {key}: {value}" for key, value in facts.items())
        sections.append("Known user facts (use them naturally, don't recite):\n" + fact_lines)

    sections.append(CRITICAL_RULES)
    return "\n\n".join(sections)
