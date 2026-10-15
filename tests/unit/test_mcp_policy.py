import secrets
import time
from uuid import uuid4
import pytest
from pydantic import SecretStr, ValidationError
from app.mcp.client import MCPClient, capability
from app.mcp.server import verify_capability
from app.schemas.tools import ReadNote, SkillManifest, ToolRequest, WriteNote, public_catalog


@pytest.mark.parametrize('resource', ['../secret', 'https://example.com', 'C:\\secret', '/etc/passwd', 'other/tenant', '', 'A', 1])
def test_semantic_resource_schema_rejects_paths_urls_and_non_slugs(resource):
    with pytest.raises(ValidationError):
        ReadNote(resource=resource)


@pytest.mark.parametrize('args', [{'resource': 'valid', 'approved': True}, {'resource': 'valid', 'endpoint': 'https://example.com'},
                                  {'resource': 'valid', 'tenant_id': str(uuid4())}, {'resource': 'valid', 'text': 7},
                                  {'resource': 'valid', 'text': 'x' * 4097}])
def test_extra_keys_and_type_coercion_are_not_allowed(args):
    with pytest.raises(ValidationError):
        WriteNote.model_validate(args)


def test_unknown_tools_and_client_approval_fields_rejected():
    for body in [{'tool': 'shell.exec', 'arguments': {}}, {'tool': 'notes.write', 'arguments': {}, 'approved': True}]:
        with pytest.raises(ValidationError):
            ToolRequest.model_validate(body)
    assert all(item['inputSchema']['additionalProperties'] is False for item in public_catalog())


@pytest.mark.parametrize('field', ['install_hook', 'packages', 'python', 'endpoint'])
def test_skill_manifest_cannot_supply_install_hooks_or_endpoints(field):
    with pytest.raises(ValidationError):
        SkillManifest.model_validate({'skill_id': 'test', 'version': '1.0.0', 'description': 'data', 'instructions': 'data',
                                      'tools': ['notes.read'], 'required_permissions': ['notes:read'], field: 'untrusted'})


def test_capability_is_bound_to_audience_scope_tenant_arguments_and_expiry():
    token, tenant, call_id = secrets.token_hex(32), uuid4(), uuid4()
    args = {'resource': 'test'}
    claims = capability(token, 'notes.read', args, tenant, call_id, 'a' * 64)
    assert verify_capability(claims, token, 'notes.read', args) == (tenant, call_id)
    for changed in [dict(claims, aud='other-service'), dict(claims, tenant=str(uuid4())),
                    dict(claims, tool='notes.write'), dict(claims, expires=int(time.time()) - 1)]:
        with pytest.raises(ValueError):
            verify_capability(changed, token, 'notes.read', args)
    with pytest.raises(ValueError):
        verify_capability(claims, token, 'notes.read', {'resource': 'changed'})
    with pytest.raises(ValueError):
        verify_capability(claims, secrets.token_hex(32), 'notes.read', args)


def test_mcp_child_does_not_inherit_privileged_credentials(settings, monkeypatch):
    monkeypatch.setenv('AGENTFORGE_ADMIN_TOKEN', 'must-not-inherit')
    monkeypatch.setenv('PYTHONPATH', 'must-not-inherit')
    monkeypatch.setenv('HTTP_PROXY', 'must-not-inherit')
    settings = settings.model_copy(update={'mcp_server_token': SecretStr(secrets.token_hex(32))})
    env = MCPClient(settings).environment()
    assert not {'AGENTFORGE_ADMIN_TOKEN', 'PYTHONPATH', 'HTTP_PROXY', 'AGENTFORGE_CAPABILITY_APPROVER_TOKEN'} & env.keys()
    assert env['AGENTFORGE_MCP_SERVER_TOKEN'] == settings.mcp_server_token.get_secret_value()
