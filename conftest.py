import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from app.services import llm_quota


@pytest.fixture(autouse=True)
def isolated_llm_quota(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_quota, "QUOTA_PATH", tmp_path / "llm_quota.json")
    monkeypatch.setattr(llm_quota, "LIMIT", 6)
    llm_quota.reset()
