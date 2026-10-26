"""Test configuration: isolated SQLite DB + no Gemini key, set before app modules import."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="courtvision-test-"))
os.environ["COURTVISION_DB"] = str(_tmp / "test.db")
os.environ["COURTVISION_MODEL"] = str(_tmp / "no_model.joblib")
os.environ["GEMINI_API_KEY"] = ""
os.environ["GEMINI_PROVIDER"] = "sdk"  # never call the real agy CLI or API from tests
os.environ["REFRESH_ON_STARTUP"] = "0"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def demo_db():
    """Fictional demo league in the temp DB (no network, no trained model -> baseline path)."""
    from data import demo_data, repository
    demo_data.generate(seed=3)
    repository.clear_cache()
    return True
