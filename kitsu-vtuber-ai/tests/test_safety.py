from __future__ import annotations

import asyncio

from libs.safety import ModerationPipeline


def test_moderation_blocks_prompt() -> None:
    pipeline = ModerationPipeline(
        pre_blocklist=["badword"],
        post_blocklist=["other"],
    )
    result = asyncio.run(pipeline.guard_prompt("this has badword inside"))
    assert result.allowed is False
    assert result.reason is not None and result.reason.startswith("pre_block")
    assert "fofinho" in result.sanitized_text


def test_moderation_allows_clean_text() -> None:
    pipeline = ModerationPipeline(
        pre_blocklist=["badword"],
        post_blocklist=["other"],
    )
    prompt_result = asyncio.run(pipeline.guard_prompt("hello there"))
    assert prompt_result.allowed is True
    response_result = asyncio.run(pipeline.guard_response("totally safe"))
    assert response_result.allowed is True


def test_moderation_sanitises_response() -> None:
    pipeline = ModerationPipeline(
        pre_blocklist=["badword"],
        post_blocklist=["kill"],
    )
    result = asyncio.run(pipeline.guard_response("please kill"))
    assert result.allowed is False
    assert result.reason is not None and result.reason.startswith("post_block")
    assert "fofinho" in result.sanitized_text
