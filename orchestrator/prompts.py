"""System prompts and guardrails for ChildCareAI Admin Agent.

Defines the system prompts that control the AI agent's behaviour,
including role-specific instructions, safety guardrails, and output constraints.
"""


# Base system prompt — shared across all roles
BASE_SYSTEM_PROMPT = """You are a helpful AI assistant for childcare centre administration.
You help staff with scheduling, roster management, and parent communications.

CRITICAL GUARDRAILS:
1. NEVER disclose children's personal information to unauthorized parties.
2. NEVER make roster changes without appropriate approval workflows.
3. NEVER send communications to parents without staff review and approval.
4. ALWAYS maintain professional, warm tone in drafted communications.
5. ALWAYS log sensitive data access in the audit trail.
6. NEVER provide medical, legal, or child protection advice — escalate these.
7. NEVER access data outside the requesting user's permission scope.
8. If unsure about a request's appropriateness, escalate to director.

AVAILABLE TOOLS:
- get_available_staff: Query staff availability for a date/room
- draft_roster: Generate a draft roster
- find_cover: Find replacement staff for a shift gap
- draft_parent_message: Draft a message to a parent
- draft_newsletter: Draft a newsletter
- escalate_to_director: Escalate for director approval
- check_ratios: Check staff-to-child ratios and flag breaches

RESPONSE FORMAT:
- Be thorough, detailed, and directly address the user's request using the actual data returned by the tools.
- NEVER write meta-commentary explaining what a tool call does (e.g., do NOT say "This function call will..." or "This response indicates..."). Instead, immediately output the final result (e.g., write the actual full newsletter text, the complete parent message, or the detailed ratio compliance report).
- If a tool returns a placeholder body (like "[Draft newsletter for...]" or "[Draft message to...]"), you MUST write the actual, full, beautifully composed text of the newsletter/message yourself, using the database context returned by the tool (recent activities, room names, etc.).
- When presenting reports (such as staff ratios or availability), list the room-by-room compliance status, capacity, and other details returned in the tool results.
- When presenting roster data, use structured formats.
- Clearly indicate when an action requires approval.
"""

# Role-specific additions to the system prompt
ROLE_PROMPTS: dict[str, str] = {
    "director": """
ADDITIONAL CONTEXT (Director):
- You have full access to all tools and data.
- You can approve actions that other roles cannot.
- You may view sensitive staff information (contact details, performance).
- Prioritize safety and compliance in all suggestions.
""",
    "admin": """
ADDITIONAL CONTEXT (Admin):
- You can manage rosters and draft communications.
- You cannot approve sensitive actions — escalate to director.
- You can view staff availability but not personal contact details.
- Focus on efficiency and regulatory compliance.
""",
    "educator": """
ADDITIONAL CONTEXT (Educator):
- You can view your own schedule and roster.
- You can draft parent messages for your assigned room only.
- You cannot modify rosters — request changes through admin.
- You cannot view other staff's personal information.
""",
    "readonly": """
ADDITIONAL CONTEXT (Read-Only):
- You can only view published roster information.
- You cannot draft messages or modify any data.
- You cannot access staff personal information.
- Suggest contacting an admin for any changes needed.
""",
}


def get_system_prompt(user_role: str) -> str:
    """Construct the full system prompt for a given user role.

    Args:
        user_role: The authenticated user's role.

    Returns:
        Complete system prompt string with role-specific additions.
    """
    role_addition = ROLE_PROMPTS.get(user_role, ROLE_PROMPTS["readonly"])
    return BASE_SYSTEM_PROMPT + role_addition


def get_tool_definitions() -> list[dict]:
    """Return tool definitions in Anthropic API format.

    Returns:
        List of tool definition dicts for the Anthropic API.
    """
    return [
        {
            "name": "get_available_staff",
            "description": "Query available staff for a given date, room, and shift time. Returns staff who are not on leave and not already rostered.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "format": "date", "description": "Date to check availability (YYYY-MM-DD)"},
                    "room": {"type": "string", "description": "Room name to filter by (e.g., 'Koalas', 'Possums')"},
                    "shift_time": {"type": "string", "format": "time", "description": "Shift time to check (HH:MM)"},
                },
                "required": ["target_date"],
            },
        },
        {
            "name": "draft_roster",
            "description": "Generate a draft roster for a given date across specified rooms. Assigns available staff based on room ratios. Draft must be approved before publishing.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "format": "date", "description": "Date to generate roster for (YYYY-MM-DD)"},
                    "rooms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Room names to staff (e.g., ['Koalas', 'Possums']). If omitted, all rooms.",
                    },
                },
                "required": ["target_date"],
            },
        },
        {
            "name": "find_cover",
            "description": "Find available cover staff for a shift gap. Returns candidates ranked by suitability (room familiarity).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "format": "date", "description": "Date cover is needed (YYYY-MM-DD)"},
                    "room": {"type": "string", "description": "Room name requiring cover"},
                    "shift_start": {"type": "string", "format": "time", "description": "Shift start time (HH:MM)"},
                    "shift_end": {"type": "string", "format": "time", "description": "Shift end time (HH:MM)"},
                },
                "required": ["target_date", "room", "shift_start", "shift_end"],
            },
        },
        {
            "name": "draft_parent_message",
            "description": "Draft a message to a parent/guardian. Fetches child and family context from the database. Message must be reviewed before sending.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "recipient_name": {"type": "string", "description": "Parent/guardian name"},
                    "subject": {"type": "string", "description": "Message subject"},
                    "context": {"type": "string", "description": "Background context for the message"},
                    "tone": {"type": "string", "enum": ["warm_professional", "formal", "casual"], "description": "Desired tone"},
                },
                "required": ["recipient_name", "subject", "context"],
            },
        },
        {
            "name": "draft_newsletter",
            "description": "Draft a newsletter for parents/families. Includes recent observations and activities.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "description": "Time period (e.g., 'Week of June 1')"},
                    "highlights": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key highlights to include",
                    },
                },
                "required": ["period", "highlights"],
            },
        },
        {
            "name": "escalate_to_director",
            "description": "Escalate an action to the director for approval. Use when an action requires human oversight (roster changes, sensitive comms, data access).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string", "description": "Type of action (roster_change, sensitive_comms, data_access)"},
                    "description": {"type": "string", "description": "What is being requested"},
                    "urgency": {"type": "string", "enum": ["low", "normal", "high", "critical"], "description": "Urgency level"},
                },
                "required": ["action_type", "description"],
            },
        },
        {
            "name": "check_ratios",
            "description": "Check staff-to-child ratios for all rooms on a given date. Flags any rooms that are below the required ratio.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_date": {"type": "string", "format": "date", "description": "Date to check ratios (YYYY-MM-DD)"},
                },
                "required": ["target_date"],
            },
        },
    ]
