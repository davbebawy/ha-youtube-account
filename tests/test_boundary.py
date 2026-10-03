"""The account integration must not depend on YouTube on TV's code."""

from __future__ import annotations

import ast
import json
from pathlib import Path

PACKAGE = Path(__file__).parent.parent / "custom_components" / "youtube_account"


def test_no_youtube_on_tv_import() -> None:
    # It plays through Home Assistant (media_player.play_media) only.
    for path in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any("youtube_on_tv" in name for name in names), path.name


def test_no_youtube_on_tv_dependency() -> None:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    for key in ("dependencies", "after_dependencies"):
        assert "youtube_on_tv" not in manifest.get(key, [])
