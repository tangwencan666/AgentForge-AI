"""Test-only authorization double, installed only with explicit MockTransport."""
class TransportPermitStub:
    async def commit(self, config, body):
        pass


def authorize_mock_transport(monkeypatch):
    monkeypatch.setattr('app.providers.openai_compatible.require_dispatch', lambda supplied: TransportPermitStub())
