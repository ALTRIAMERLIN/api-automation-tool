import httpx
import pytest


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """No test may touch the network (SPEC section 20)."""

    def _refuse(self, request):  # noqa: ARG001
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)
