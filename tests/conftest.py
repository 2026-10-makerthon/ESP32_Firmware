import pytest
from harness.native import Native


@pytest.fixture(scope="session")
def native_backend():
    # Windows cannot overwrite a DLL already loaded by a previous module fixture.
    return Native()
