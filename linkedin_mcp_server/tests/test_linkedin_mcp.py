"""Tests for the LinkedIn Browser Automation MCP Server."""

from __future__ import annotations

import json
from pathlib import Path

from linkedin_mcp.linkedin_automator import LinkedInAutomator
from linkedin_mcp.profile_store import CandidateProfileStore
from linkedin_mcp.server import (
    get_candidate_profile,
    set_automator,
    update_candidate_profile,
)


def test_profile_matching_and_persistence(tmp_path: Path) -> None:
    profile_file = tmp_path / "profile.json"
    store = CandidateProfileStore(profile_path=profile_file)
    store.update(
        {
            "first_name": "Alex",
            "last_name": "Rivera",
            "email": "alex@example.com",
            "phone": "555-123-4567",
            "city": "San Francisco, CA",
            "years_of_experience": {
                "default": "4",
                "python": "6",
                "pytorch": "3",
            },
            "work_authorization": {
                "authorized_to_work": "Yes",
                "require_sponsorship": "No",
            },
            "compensation": {
                "expected_salary": "175000",
            },
        }
    )

    assert store.match_question("Mobile phone number *") == "555-123-4567"
    assert store.match_question("Email address") == "alex@example.com"
    assert (
        store.match_question("How many years of work experience do you have with Python?")
        == "6"
    )
    assert (
        store.match_question("How many years of work experience do you have with Kubernetes?")
        == "4"
    )
    assert (
        store.match_question(
            "Are you legally authorized to work in the United States?",
            field_type="radio",
            options=["Yes", "No"],
        )
        == "Yes"
    )
    assert (
        store.match_question(
            "Will you now or in the future require sponsorship for employment visa status?",
            field_type="select",
            options=["Select an option", "Yes", "No"],
        )
        == "No"
    )
    assert store.match_question("What is your desired salary?") == "175000"


def test_build_linkedin_search_url(tmp_path: Path) -> None:
    automator = LinkedInAutomator(
        profile_store=CandidateProfileStore(profile_path=tmp_path / "profile.json")
    )
    url = automator.build_search_url(
        keywords="Machine Learning Engineer",
        location="San Francisco",
        easy_apply_only=True,
        workplace_type="remote",
        date_posted="week",
    )
    assert "keywords=Machine+Learning+Engineer" in url
    assert "location=San+Francisco" in url
    assert "f_AL=true" in url
    assert "f_WT=2" in url
    assert "f_TPR=r604800" in url


def test_mcp_profile_tools(tmp_path: Path) -> None:
    automator = LinkedInAutomator(
        profile_store=CandidateProfileStore(profile_path=tmp_path / "profile.json")
    )
    set_automator(automator)

    updated = json.loads(
        update_candidate_profile(
            json.dumps({"first_name": "Jordan", "phone": "555-999-0000"})
        )
    )
    assert updated["first_name"] == "Jordan"

    current = json.loads(get_candidate_profile())
    assert current["profile"]["phone"] == "555-999-0000"
