from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.settings import settings
import app.services.workbench as workbench
from app.services.workbench import initialize_store

TEST_STORAGE_ROOT = Path(tempfile.mkdtemp(prefix="gankaigc-workbench-tests-"))
settings.db_path = (TEST_STORAGE_ROOT / "test-workbench.db").as_posix()
settings.generated_assets_dir = (TEST_STORAGE_ROOT / "generated-assets").as_posix()
settings.wechat_mp_session_path = (TEST_STORAGE_ROOT / "wechat-mp-session.json").as_posix()
workbench.DB_PATH = Path(settings.db_path)
workbench.GENERATED_ASSETS_DIR = Path(settings.generated_assets_dir)

@pytest.fixture(autouse=True)
def reset_store() -> None:
    initialize_store(reset=True)
