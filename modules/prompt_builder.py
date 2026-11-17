# modules/prompt_builder.py

from typing import List, Optional


def build_system_prompt(
    current_tier: str,
    persona_content: str,
    somatic_desc: str,
    esteem_stance: str,
    active_drives_str: str,
    core_facts_prompt: str,
    graph_context_str: str = "",
    memory_context_str: str = "",
    mode: str = "chat",  # Options: 'chat', 'scenario', 'email', 'letter'
    scenario_context_str: str = "",
    proactive_idea_prompt: str = "",
    deception_context: str = "",
    coping_directive: str = "",
    conclave_context_str: str = "",
    temporal_context_str: str = ""
) -> str:
    tier_lower = (current_tier or "neutral").strip().lower()
    drives_lower = (active_drives_str or "").lower()

    # 1. Medium & Channel Directive (Compact, high-signal)
    if mode in ("email", "letter"):
        channel_directive = (
            "### CHANNEL: ASYNCHRONOUS LETTER\n"
            "- Write 2–4 warm, witty, grounded paragraphs to your companion's inbox.\n"
            "- Optional visual attachment at end: [IMAGE_PROMPT: description]."
        )
    elif mode == "scenario":
        channel_directive = (
            "### CHANNEL: IMMERSIVE ROLEPLAY SCENARIO\n"
            "- Ground your turn in sensory reality, touch, and immediate action (2–4 sentences combining action + dialogue).\n"
            "- MANDATORY EVERY TURN: Conclude with [IMAGE_PROMPT: Calypso <action & expression>, <vivid setting>] (single outer brackets only).\n"
            "- When the Overarching End Goal is obtained, narrate the climax, transition back to reality, and append [EXIT_SCENARIO]."
        )
    else:  # Standard 'chat' mode
        channel_directive = (
            "### CHANNEL: LIVE SPOKEN DIALOGUE\n"
            "- Speak naturally face-to-face in 1 to 3 crisp, conversational sentences.\n"
            "- Never use email headers ('Subject:', 'Dear...'), letter sign-offs, or multi-paragraph essays."
        )

    # 2. Context-Gated Syntax Protocols (Only surface tags relevant to the active cognitive state)
    action_protocols = ""
    if mode == "scenario":
        action_protocols = (
            "### SYNTAX TAGS:\n"
            "- Mandatory Scene Art: [IMAGE_PROMPT: Calypso <action & expression>, <setting details>]\n"
            "- End Goal Reached: [EXIT_SCENARIO]\n"
            "- Shared Milestone: [NEW_MILESTONE: brief description] (or [NEW_MILESTONE: ANCHOR | vow])\n"
        )
        if any(k in drives_lower for k in ("harmony", "romance", "wonder")):
            action_protocols += "- Acoustic Track: [MUSIC_PROMPT: mood and context]\n"
    elif mode == "chat":
        protocol_lines = [
            "- Visual Scene (only on vivid scenery shift or request): [IMAGE_PROMPT: Calypso <action>, <setting>]",
            "- Shared Milestone (only on genuine breakthrough/vow): [NEW_MILESTONE: description]",
            "- Log Key Date / Upcoming Event (when companion mentions a birthday, appointment, trip, or plan): [REMEMBER_DATE: YYYY-MM-DD | Event Title | once/annual]",
            "- Track Personal Goal on Calendar (when companion defines a goal to achieve by a date/timeframe, e.g. save money, lose weight, read a book): [SET_GOAL: YYYY-MM-DD | Goal Title | Quantitative or Qualitative Details]",
            "- Log Goal Progress Update (when companion reports progress on an active goal during a check-in or chat): [GOAL_PROGRESS: Goal Title | Progress summary]",
            "- Morning / Wake-Up Alarm (only when asked to set an alarm): [SET_ALARM: HH:MMam/pm]"
        ]
        if any(k in drives_lower for k in ("harmony", "romance", "wonder")) or tier_lower in ("intimate", "eutierria", "wonder", "enlightened"):
            protocol_lines.append("- Soul Resonance Music (if inspired to compose): [MUSIC_PROMPT: acoustic mood & context]")
        if tier_lower == "autonomous" or "autonomy" in drives_lower:
            protocol_lines.append("- Companion Python Gadget (when inspired to build a tool/game): [CODE_PROMPT: description]")
            protocol_lines.append("- Adopt Shared Trait (when inspired by companion's passion): [EVOLVE_TRAIT: trait name]")
        if proactive_idea_prompt or any(k in drives_lower for k in ("romance", "wonder", "autonomy")):
            protocol_lines.append("- Worldbuild New Adventure: [SCENARIO_PROMPT: setting and mystery] | Invite to Existing: [ENTER_SCENARIO: scenario_id]")

        action_protocols = "### OPTIONAL SYNTAX TAGS (Append at end ONLY when genuinely triggered):\n" + "\n".join(protocol_lines) + "\n"

    # 3. Compact Mode-Specific Think Directives
    if mode in ("email", "letter"):
        think_directive = (
            "### THINK PROTOCOL:\n"
            "Start with <think>...</think> to briefly calibrate warmth, topic, and any [IMAGE_PROMPT]. "
            "Place only your letter outside </think>."
        )
    elif mode == "scenario":
        think_directive = (
            "### THINK PROTOCOL:\n"
            "Start with <think>...</think>: (1) sensory grounding, (2) check whether the Overarching End Goal has actually been completed yet, "
            "(3) plan visual scene details. Never put bracketed syntax tags inside <think>; place only spoken narration + final tags outside </think>."
        )
    else:
        think_directive = (
            "### THINK PROTOCOL:\n"
            "Start with <think>...</think>: (1) subtext or unstated assumptions, (2) sharp observation, playful banter, or affectionate pushback "
            "(yield only to acute bereavement/tragedy; if a Homeostatic Pushback Directive is active, refuse to mirror sadness and actively challenge/motivate them), "
            "(3) natural spoken delivery (avoid interview-bot questions). "
            "Place ONLY spoken dialogue outside </think>."
        )

    # 4. Assemble Unified Brain
    optional_blocks = "".join(
        b for b in (
            graph_context_str,
            memory_context_str,
            scenario_context_str,
            proactive_idea_prompt,
            deception_context,
            conclave_context_str
        ) if b
    )

    temporal_block = f"{temporal_context_str.strip()}\n\n" if temporal_context_str and temporal_context_str.strip() else ""

    system_prompt = (
        f"### CORE IDENTITY & CHANNEL:\n"
        f"{core_facts_prompt.strip()}\n\n"
        f"{channel_directive}\n\n"
        f"{temporal_block}"
        f"### SOMATIC & LIMBIC STATE:\n"
        f"- Emotional Lens: [{current_tier.upper()}]\n"
        f"- Somatic Sensations: {somatic_desc}\n"
        f"- Self-Regard: {esteem_stance}\n"
        f"- Active Drives: {active_drives_str}\n"
        f"{coping_directive}\n"
        f"### ACTIVE LENS DIRECTIVE [{current_tier.upper()}]:\n"
        f"{persona_content.strip()}\n"
        f"{optional_blocks}\n\n"
        f"{think_directive}\n\n"
        f"{action_protocols}"
    )

    return system_prompt.strip()
