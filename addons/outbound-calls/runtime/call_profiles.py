"""Deterministic model and voice framing profiles for call follow-ups."""

OUTCOMES = ("complete", "still_running", "failed_or_blocked", "unclear")

_BASE_PROFILES = {
    "default": {
        "model": "gpt-6.1-sol",
        "effort": "medium",
        "service_tier": "fast",
        "voice_instructions": (
            "Have a substantive, reasoned conversation grounded in the supplied "
            "briefing and verified evidence."
        ),
    },
    "complete": {
        "model": "gpt-6.1-terra",
        "effort": "medium",
        "service_tier": "default",
        "voice_instructions": (
            "Lead with verified completion, checks, and artifacts; mention a "
            "next step only if useful."
        ),
    },
    "still_running": {
        "model": "gpt-6.1-terra",
        "effort": "high",
        "service_tier": "fast",
        "voice_instructions": (
            "Give the current checkpoint and evidence explaining the delay; "
            "distinguish known causes from suspected or unknown causes."
        ),
    },
    "failed_or_blocked": {
        "model": "gpt-6.1-sol",
        "effort": "medium",
        "service_tier": "fast",
        "voice_instructions": (
            "State the verified failure or blocker; separate causes from "
            "hypotheses, then offer options and identify any specific decision needed."
        ),
    },
    "unclear": {
        "model": "gpt-6.1-sol",
        "effort": "medium",
        "service_tier": "fast",
        "voice_instructions": (
            "Describe the missing or conflicting evidence; do not declare failure. "
            "State the next verification step or question."
        ),
    },
}

_ALLOWED_VALUES = {
    "model": ("gpt-6.1-sol", "gpt-6.1-terra"),
    "effort": ("medium", "high"),
    "service_tier": ("default", "fast"),
}


def validate_profiles(overrides):
    """Validate and copy outcome-specific profile overrides."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise ValueError("profile overrides must be a dictionary or None")

    known_profiles = {"default", *OUTCOMES}
    validated = {}
    for outcome, fields in overrides.items():
        if outcome not in known_profiles:
            raise ValueError(f"unknown profile outcome: {outcome!r}")
        if not isinstance(fields, dict):
            raise ValueError(f"profile for {outcome!r} must be a dictionary")

        validated_fields = {}
        for field, value in fields.items():
            if field not in _ALLOWED_VALUES:
                raise ValueError(f"invalid profile field: {field!r}")
            if value not in _ALLOWED_VALUES[field]:
                raise ValueError(f"invalid {field} value: {value!r}")
            validated_fields[field] = value
        validated[outcome] = validated_fields
    return validated


def select_profile(outcome=None, overrides=None):
    """Return an independent profile, applying only validated overrides."""
    if outcome is None:
        selected = "default"
    elif isinstance(outcome, str) and outcome in OUTCOMES:
        selected = outcome
    else:
        raise ValueError(f"unknown outcome: {outcome!r}")

    profiles = validate_profiles(overrides)
    profile = dict(_BASE_PROFILES[selected])
    profile.update(profiles.get(selected, {}))
    profile["outcome"] = selected
    return profile
