from __future__ import annotations

from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_httpx_is_declared_as_runtime_dependency_for_wechat_mp_client() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    runtime_dependencies = pyproject["project"]["dependencies"]
    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]

    assert "httpx>=0.28.0,<1.0.0" in runtime_dependencies
    assert "httpx>=0.28.0,<1.0.0" not in dev_dependencies
