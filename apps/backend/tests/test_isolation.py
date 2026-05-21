from __future__ import annotations

from pathlib import Path

import pytest

from app.core.settings import settings
from app.services import workbench


def test_backend_tests_use_isolated_storage_paths() -> None:
    assert settings.db_path != "C:/tmp/gankaigc-wechat-workbench.db"
    assert settings.generated_assets_dir != "C:/tmp/gankaigc-wechat-workbench-assets"


def test_initialize_store_reset_is_blocked_for_default_persistent_db(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(workbench, "DB_PATH", Path("C:/tmp/gankaigc-wechat-workbench.db"))
    monkeypatch.setattr(workbench, "GENERATED_ASSETS_DIR", tmp_path / "generated-assets")

    with pytest.raises(RuntimeError, match="Refusing to reset persistent store"):
        workbench.initialize_store(reset=True)


def test_initialize_store_reset_allows_isolated_test_db(monkeypatch, tmp_path) -> None:
    isolated_db = tmp_path / "isolated.db"
    monkeypatch.setattr(workbench, "DB_PATH", isolated_db)
    monkeypatch.setattr(workbench, "GENERATED_ASSETS_DIR", tmp_path / "generated-assets")

    workbench.initialize_store(reset=True)

    assert isolated_db.exists()
