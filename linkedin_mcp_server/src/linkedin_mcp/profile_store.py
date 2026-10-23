"""Candidate profile storage and intelligent Easy Apply form question matcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

DEFAULT_PROFILE: Dict[str, Any] = {
    "first_name": "",
    "last_name": "",
    "email": "",
    "phone": "",
    "phone_country_code": "United States (+1)",
    "city": "",
    "linkedin_url": "",
    "github_url": "",
    "portfolio_url": "",
    "resume_path": "",
    "headline": "",
    "summary": "",
    "years_of_experience": {
        "default": "3",
    },
    "work_authorization": {
        "authorized_to_work": "Yes",
        "require_sponsorship": "No",
        "willing_to_relocate": "Yes",
        "remote_preference": "Yes",
    },
    "compensation": {
        "expected_salary": "",
        "notice_period_days": "14",
    },
    "custom_answers": {},
}


class CandidateProfileStore:
    """Loads, updates, and matches candidate profile attributes to LinkedIn Easy Apply questions."""

    def __init__(self, profile_path: Optional[Path] = None) -> None:
        env_path = os.getenv("LINKEDIN_PROFILE_PATH", "./profile.json")
        self.profile_path = (profile_path or Path(env_path)).expanduser().resolve()
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        merged = json.loads(json.dumps(DEFAULT_PROFILE))
        if self.profile_path.exists():
            try:
                loaded = json.loads(self.profile_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for k, v in loaded.items():
                        if isinstance(v, dict) and isinstance(merged.get(k), dict):
                            merged[k].update(v)
                        else:
                            merged[k] = v
            except (OSError, json.JSONDecodeError):
                pass
        return merged

    def save(self) -> None:
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def update(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in updates.items():
            if isinstance(v, dict) and isinstance(self.data.get(k), dict):
                self.data[k].update(v)
            else:
                self.data[k] = v
        self.save()
        return self.data

    def match_question(
        self,
        label: str,
        field_type: str = "text",
        options: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Heuristically match a LinkedIn Easy Apply question label to a profile answer."""
        q = label.strip().lower()
        if not q:
            return None

        # 1. Check exact or substring custom_answers first
        custom = self.data.get("custom_answers", {})
        for pattern, ans in custom.items():
            if pattern.lower() in q and str(ans).strip():
                return self._pick_best_option(str(ans), options)

        # 2. Direct contact fields
        if "first name" in q and self.data.get("first_name"):
            return str(self.data["first_name"])
        if "last name" in q and self.data.get("last_name"):
            return str(self.data["last_name"])
        if "email" in q and self.data.get("email"):
            return str(self.data["email"])
        if ("phone country" in q or "country code" in q) and self.data.get("phone_country_code"):
            return self._pick_best_option(str(self.data["phone_country_code"]), options)
        if ("phone" in q or "mobile" in q) and self.data.get("phone"):
            return str(self.data["phone"])
        if ("city" in q or "location" in q) and self.data.get("city"):
            return str(self.data["city"])

        # 3. Links / URLs
        if "linkedin" in q and self.data.get("linkedin_url"):
            return str(self.data["linkedin_url"])
        if "github" in q and self.data.get("github_url"):
            return str(self.data["github_url"])
        if ("website" in q or "portfolio" in q) and self.data.get("portfolio_url"):
            return str(self.data["portfolio_url"])

        # 4. Work authorization & sponsorship
        work_auth = self.data.get("work_authorization", {})
        if ("authorized" in q or "legally" in q or "eligible to work" in q) and work_auth.get(
            "authorized_to_work"
        ):
            return self._pick_best_option(str(work_auth["authorized_to_work"]), options)
        if ("sponsorship" in q or "visa" in q) and work_auth.get("require_sponsorship"):
            return self._pick_best_option(str(work_auth["require_sponsorship"]), options)
        if "relocat" in q and work_auth.get("willing_to_relocate"):
            return self._pick_best_option(str(work_auth["willing_to_relocate"]), options)
        if ("remote" in q or "hybrid" in q or "on-site" in q or "onsite" in q) and work_auth.get(
            "remote_preference"
        ):
            return self._pick_best_option(str(work_auth["remote_preference"]), options)

        # 5. Compensation & notice period
        comp = self.data.get("compensation", {})
        if ("salary" in q or "compensation" in q or "pay" in q) and comp.get("expected_salary"):
            return str(comp["expected_salary"])
        if ("notice" in q or "start date" in q or "how soon" in q) and comp.get(
            "notice_period_days"
        ):
            return str(comp["notice_period_days"])

        # 6. Years of experience ("How many years of work experience do you have with X?")
        yoe = self.data.get("years_of_experience", {})
        if "years" in q or "experience" in q:
            for skill, years in yoe.items():
                if skill != "default" and skill.lower() in q:
                    return self._pick_best_option(str(years), options)
            if yoe.get("default"):
                return self._pick_best_option(str(yoe["default"]), options)

        return None

    @staticmethod
    def _pick_best_option(desired: str, options: Optional[List[str]]) -> str:
        """If the field has finite options (select/radio), return the closest matching option."""
        if not options:
            return desired
        desired_low = desired.strip().lower()
        for opt in options:
            if opt.strip().lower() == desired_low:
                return opt
        for opt in options:
            if desired_low in opt.strip().lower() or opt.strip().lower() in desired_low:
                return opt
        return desired
