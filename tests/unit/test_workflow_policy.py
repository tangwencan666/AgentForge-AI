from decimal import Decimal
import secrets
import pytest
from pydantic import ValidationError
from app.schemas.tasks import TaskCreate
from app.services.context import redact, build_context, mock_tokens
from app.services.tool_policy import ToolGrant, authorize_tool
from app.core.errors import AppError


@pytest.mark.parametrize('changes', [{'execution_mode':'unrestricted'},{'max_iterations':9},{'max_calls':33},{'max_tokens':100001},
    {'max_budget_usd':'1.01'},{'timeout_seconds':901},{'mock_options':{'latency_ms':2001}},{'goal':''},{'approved':True}])
def test_task_limits_and_real_mode_are_not_bypassable(changes):
    with pytest.raises(ValidationError):
        TaskCreate(**({'goal':'test','execution_mode':'mock'} | changes))


def test_context_redacts_secrets_and_marks_truncation(settings, monkeypatch):
    secret = secrets.token_hex(32)
    monkeypatch.setenv('AGENTFORGE_MODEL_TEST', secret)
    goal = settings.admin_token.get_secret_value() + ' api_key=hidden ' + secret + ' 中文' * 4000
    context = build_context(goal,'coder',settings)
    assert secret not in str(context) and settings.admin_token.get_secret_value() not in str(context)
    assert 'api_key=hidden' not in context['goal']
    assert context['truncated'] is True
    assert len(context['goal'].encode()) <= 4096
    assert context['is_mock'] and context['source'] == 'task_goal'


@pytest.mark.parametrize('grant,role,code', [
    (ToolGrant('test',False,True,True,'user','approver'),'coder','TOOL_FORBIDDEN'),
    (ToolGrant('test',True,True,False,'user','approver'),'coder','TOOL_APPROVAL_REQUIRED'),
    (ToolGrant('test',True,True,True,'user','user'),'coder','TOOL_APPROVAL_REQUIRED'),
    (ToolGrant('test',True,True,True,'user','approver'),'reviewer','TOOL_FORBIDDEN'),
    (ToolGrant('sandbox.execute',True,True,True,'user','approver'),'coder','TOOL_UNAVAILABLE'),
])
def test_high_risk_tool_policy_never_substitutes_reviewer_for_permissions(grant,role,code):
    with pytest.raises(AppError) as error:
        authorize_tool(grant,role)
    assert error.value.code == code


def test_mock_accounting_is_explicit_simulation():
    assert mock_tokens({'x':'abc'}) > 0
    assert TaskCreate(goal='test',execution_mode='mock').max_budget_usd == Decimal('1')
