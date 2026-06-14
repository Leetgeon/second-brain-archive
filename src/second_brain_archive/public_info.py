from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class PublicInfo:
    app_name: str = "Second Brain Archive"
    operator_name: str = ""
    support_email: str = ""
    homepage_url: str = ""
    privacy_url: str = ""
    terms_url: str = ""
    jurisdiction: str = "Republic of Korea"

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.operator_name:
            errors.append("SECOND_BRAIN_OPERATOR_NAME")
        if "@" not in self.support_email:
            errors.append("SECOND_BRAIN_SUPPORT_EMAIL")
        for name, value in (
            ("SECOND_BRAIN_HOMEPAGE_URL", self.homepage_url),
            ("SECOND_BRAIN_PRIVACY_URL", self.privacy_url),
            ("SECOND_BRAIN_TERMS_URL", self.terms_url),
        ):
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.netloc:
                errors.append(name)
        return errors

    def as_dict(self) -> dict[str, str]:
        return {
            "app_name": self.app_name,
            "operator_name": self.operator_name,
            "support_email": self.support_email,
            "homepage_url": self.homepage_url,
            "privacy_url": self.privacy_url,
            "terms_url": self.terms_url,
            "jurisdiction": self.jurisdiction,
        }


def public_info() -> PublicInfo:
    values: dict[str, str] = {}
    marker = Path(__file__).with_name("public_info.json")
    if marker.is_file():
        try:
            raw = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                values = {
                    str(key): str(value)
                    for key, value in raw.items()
                    if value is not None
                }
        except (OSError, ValueError):
            values = {}

    if not getattr(sys, "frozen", False):
        base_url = os.environ.get("SECOND_BRAIN_HOMEPAGE_URL", "").rstrip("/")
        environment = {
            "app_name": os.environ.get("SECOND_BRAIN_APP_NAME", ""),
            "operator_name": os.environ.get("SECOND_BRAIN_OPERATOR_NAME", ""),
            "support_email": os.environ.get("SECOND_BRAIN_SUPPORT_EMAIL", ""),
            "homepage_url": base_url,
            "privacy_url": os.environ.get(
                "SECOND_BRAIN_PRIVACY_URL",
                f"{base_url}/privacy/" if base_url else "",
            ),
            "terms_url": os.environ.get(
                "SECOND_BRAIN_TERMS_URL",
                f"{base_url}/terms/" if base_url else "",
            ),
            "jurisdiction": os.environ.get("SECOND_BRAIN_JURISDICTION", ""),
        }
        values.update({key: value for key, value in environment.items() if value})

    allowed = PublicInfo.__dataclass_fields__
    return PublicInfo(**{key: value for key, value in values.items() if key in allowed})
