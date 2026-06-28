"""System-prompt assembly and the inbound-bearer extractor."""

from __future__ import annotations

from types import SimpleNamespace

from agent_kit.infra.identity import extract_user_jwt
from agent_kit.knowledge.skill_loader import SkillLoader
from agent_kit.prompt import build_system_prompt


def _loader_with_a_skill(tmp_path) -> SkillLoader:
    # An on-demand skill (not preloaded) so it lands in the catalog.
    (tmp_path / "credit_hold.skill.md").write_text(
        "---\n"
        "apiName: credit_hold\n"
        "description: Use when a customer may be over their credit limit.\n"
        "appliesTo:\n"
        "  objectTypes: [CreditProfile]\n"
        "  actions: [raiseException]\n"
        "---\n"
        "# Credit Hold\n\nStep 1. do the thing.\n"
    )
    return SkillLoader(tmp_path)


def test_build_system_prompt_includes_catalog_and_preamble(tmp_path):
    prompt = build_system_prompt(preamble="X", loader=_loader_with_a_skill(tmp_path))
    assert prompt.startswith("X\n\n")  # preamble prepended, blank line after
    assert "credit_hold" in prompt  # the on-demand catalog entry
    assert "Use when a customer may be over their credit limit." in prompt
    assert "load_skill(name)" in prompt  # the shared boilerplate


def test_build_system_prompt_empty_preamble_omits_it(tmp_path):
    prompt = build_system_prompt(loader=_loader_with_a_skill(tmp_path))
    assert not prompt.startswith("X")
    assert "credit_hold" in prompt


def test_extract_user_jwt_strips_bearer_scheme():
    ctx = SimpleNamespace(request_headers={"Authorization": "Bearer abc"})
    assert extract_user_jwt(ctx) == "abc"


def test_extract_user_jwt_returns_raw_token_without_scheme():
    ctx = SimpleNamespace(request_headers={"Authorization": "abc"})
    assert extract_user_jwt(ctx) == "abc"


def test_extract_user_jwt_none_when_absent():
    assert extract_user_jwt(SimpleNamespace(request_headers={})) is None
    assert extract_user_jwt(SimpleNamespace(request_headers=None)) is None
    assert extract_user_jwt(None) is None


def test_extract_user_jwt_honours_custom_header_name():
    ctx = SimpleNamespace(request_headers={"X-User-Token": "Bearer xyz"})
    assert extract_user_jwt(ctx, header_name="X-User-Token") == "xyz"
    assert extract_user_jwt(ctx) is None  # default Authorization absent
