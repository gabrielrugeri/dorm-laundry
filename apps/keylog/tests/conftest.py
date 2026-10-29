import pytest


@pytest.fixture(autouse=True)
def keys_enabled(settings):
    """Key handling is on hold by default (KEYS_ENABLED=false); its tests run
    with it switched on so the code keeps working for when it returns."""
    settings.KEYS_ENABLED = True
