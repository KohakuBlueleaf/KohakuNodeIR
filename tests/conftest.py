import pytest
from pathlib import Path


@pytest.fixture
def fixture_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture(fixture_dir):
    def _load(name):
        return (fixture_dir / name).read_text(encoding="utf-8")
    return _load
