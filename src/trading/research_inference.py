"""Explicit local prompt profiles; these confer no execution permissions."""
# ruff: noqa: E501

import hashlib
import json
from typing import Any

from trading.research_protocol import ROLES, Role, prompt
from trading.research_resources import ELASTIC_CPU_RUNTIME, elastic_resources_valid

MINISTRAL_REASONING = "hf.co/mistralai/Ministral-3-8B-Reasoning-2512-GGUF:Q4_K_M"
MINISTRAL_TEXT = "trading-research-ministral3-8b-text:q4km-v1"
MINISTRAL_MODELS = (MINISTRAL_REASONING, MINISTRAL_TEXT)
BASE_PROFILE = "role-contract-only"
MINISTRAL_PROFILE = "ministral-official-reasoning-prefix-v1"
PROFILES = (BASE_PROFILE, MINISTRAL_PROFILE)
CPU_RUNTIME = "trading-cpu-two-processors-v1"


def cpu_placement_valid(
    row: dict[str, Any], model: str, digest: str, profile: str = CPU_RUNTIME
) -> bool:
    resident = row.get("model_runtime_after")
    if not isinstance(resident, list) or len(resident) != 1 or not isinstance(resident[0], dict):
        return False
    return bool(
        profile in (CPU_RUNTIME, ELASTIC_CPU_RUNTIME)
        and (profile != ELASTIC_CPU_RUNTIME or elastic_resources_valid(row.get("resource_state_after")))
        and not row.get("model_runtime_error")
        and row.get("settings", {}).get("num_gpu") == 0
        and row.get("settings", {}).get("num_thread") == (6 if profile == ELASTIC_CPU_RUNTIME else 2)
        and resident[0].get("name") == model
        and resident[0].get("digest") == digest
        and resident[0].get("size_vram") == 0
    )


# Mistral's Apache-2.0 model SYSTEM_PROMPT.txt, preserved verbatim.
# https://huggingface.co/mistralai/Ministral-3-8B-Reasoning-2512/blob/main/SYSTEM_PROMPT.txt
# The task contract appended afterward specifies the final JSON output.
MINISTRAL_PREFIX = """# HOW YOU SHOULD THINK AND ANSWER

First draft your thinking process (inner monologue) until you arrive at a response. Format your response using Markdown, and use LaTeX for any mathematical equations. Write both your thoughts and the response in the same language as the input.

Your thinking process must follow the template below:[THINK]Your thoughts or/and draft, like working through an exercise on scratch paper. Be as casual and as long as you want until you are confident to generate the response to the user.[/THINK]Here, provide a self-contained response."""


def role_prompt(role: Role, profile: str = BASE_PROFILE) -> str:
    if profile == BASE_PROFILE:
        return prompt(role)
    if profile == MINISTRAL_PROFILE:
        return MINISTRAL_PREFIX + "\n\n" + prompt(role)
    raise ValueError("Unknown inference prompt profile")


def effective_protocol_hash(profile: str = BASE_PROFILE) -> str:
    return hashlib.sha256(json.dumps([role_prompt(r, profile) for r in ROLES]).encode()).hexdigest()


def validate_profile(model: str, thinking: bool, profile: str) -> None:
    if profile not in PROFILES:
        raise ValueError("Unknown inference prompt profile")
    if profile == MINISTRAL_PROFILE and (model not in MINISTRAL_MODELS or not thinking):
        raise ValueError(
            "The native reasoning profile requires the exact Ministral reasoning model"
        )
