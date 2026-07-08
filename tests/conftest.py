import pytest
from phantom_curl.network.session import NetworkSession
from phantom_curl.models import StealthConfig


@pytest.fixture
def network_session():
    """
    Provides a NetworkSession instance configured with default stealth
    settings, and ensures it is properly closed after each test.
    """
    session = NetworkSession(StealthConfig())
    yield session
    session.close()