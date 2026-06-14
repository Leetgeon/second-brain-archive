from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PUBLIC_PROFILE = "public"
PERSONAL_PROFILE = "personal"


def distribution_profile() -> str:
    marker = Path(__file__).with_name("distribution_profile.json")
    if marker.is_file():
        try:
            value = json.loads(marker.read_text(encoding="utf-8")).get("profile")
        except (OSError, ValueError, AttributeError):
            value = None
        if value in {PUBLIC_PROFILE, PERSONAL_PROFILE}:
            return value

    if not getattr(sys, "frozen", False):
        configured = os.environ.get("SECOND_BRAIN_PROFILE", "").strip().lower()
        if configured in {PUBLIC_PROFILE, PERSONAL_PROFILE}:
            return configured
    return PERSONAL_PROFILE


def is_public_distribution() -> bool:
    return distribution_profile() == PUBLIC_PROFILE
