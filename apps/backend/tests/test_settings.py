from __future__ import annotations

from pathlib import Path

from app.core.settings import _resolve_repo_env_file


def test_resolve_repo_env_file_points_to_repo_root_env() -> None:
    env_path = _resolve_repo_env_file()

    assert env_path.name == ".env"
    assert env_path.parent == Path(__file__).resolve().parents[3]
