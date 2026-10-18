from uuid import UUID, uuid4
import os
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from app.core.errors import AppError
from app.core.security import require_admin
from app.domain.tasks import ModelOperation, AgentTask
from app.schemas.models import ModelRole
from app.schemas.tasks import TaskCreate
from app.schemas.responses import ApiResponse, envelope
from app.services.tasks import TaskService

router = APIRouter(prefix='/api/v1', tags=['P5 inference'])


@router.get('/models/policy', response_model=ApiResponse)
async def policy(request: Request, tenant=Depends(require_admin)):
    s = request.app.state.settings
    blocked = os.environ.get('AGENTFORGE_EXTERNAL_MODELS_BLOCKED', '').lower() in {'1', 'true'}
    return envelope({'real_calls_enabled': s.real_calls_enabled, 'daily_budget_usd': str(s.real_daily_budget_usd),
        'external_calls_blocked': blocked, 'real_max_retries': s.real_max_retries,
        'test_retry_policy': 'none',
        'permit_required': True, 'permit_issuance_enabled': s.single_use_permits_enabled,
        'real_worker_mode': s.real_worker_mode,
        'test_budget_usd': str(s.real_test_budget_usd), 'test_max_calls': s.real_test_max_calls,
        'adapters': ['openai_compatible', 'deepseek'], 'paid_test_status': 'permit_only' if s.single_use_permits_enabled and s.real_test_budget_usd > 0 and s.real_calls_enabled and not blocked else 'BLOCKED'})


@router.get('/models/runtime-status', response_model=ApiResponse)
async def runtime_status(request: Request, tenant=Depends(require_admin)):
    from app.services.model_runtime_status import compare_runtime_status
    return envelope(await compare_runtime_status(request.app.state.connections, request.app.state.settings))


@router.post('/model-slots/{role}/test', response_model=ApiResponse, status_code=202)
async def test_model(role: ModelRole, request: Request, idempotency_key: UUID = Header(alias='Idempotency-Key'), tenant=Depends(require_admin)):
    service = TaskService(request.app.state.connections, request.app.state.settings)
    return envelope(await service.create(tenant, idempotency_key, TaskCreate(goal='Reply with the word connected.', workflow='chat',
        chat_role=role.value, execution_mode='real', require_approval=False, max_calls=1, max_iterations=1,
        max_budget_usd=min(request.app.state.settings.real_test_budget_usd, 1) or 1), model_test=True))


@router.get('/models/metrics', response_model=ApiResponse)
async def metrics(request: Request, tenant=Depends(require_admin)):
    async with request.app.state.connections.sessions() as session:
        rows = (await session.scalars(select(ModelOperation).join(AgentTask).where(AgentTask.tenant_id == UUID(tenant))
                                     .order_by(ModelOperation.started_at.desc()).limit(2000))).all()
    groups = {}
    for row in rows:
        key = (row.role, row.provider, row.model, row.is_mock)
        g = groups.setdefault(key, {'role': row.role, 'provider': row.provider, 'model': row.model, 'is_mock': row.is_mock,
            'requests': 0, 'successes': 0, 'timeouts': 0, 'errors': 0, 'input_tokens_reported': 0, 'output_tokens_reported': 0,
            'total_tokens_reported': 0, 'usage_unknown': 0, 'estimated_cost_usd': '0', 'pending_upper_bound_usd': '0',
            'latencies_ms': [], 'first_token_ms': []})
        from decimal import Decimal
        g['requests'] += 1
        g['successes'] += row.state == 'completed'
        g['timeouts'] += row.error_code == 'MODEL_TIMEOUT'
        g['errors'] += row.state in {'failed', 'pending'}
        if row.is_mock or row.total_tokens is not None:
            g['input_tokens_reported'] += row.input_tokens
            g['output_tokens_reported'] += row.output_tokens
            g['total_tokens_reported'] += row.total_tokens if row.total_tokens is not None else row.input_tokens + row.output_tokens
            g['estimated_cost_usd'] = str(Decimal(g['estimated_cost_usd']) + row.cost)
        else:
            g['usage_unknown'] += 1
            g['pending_upper_bound_usd'] = str(Decimal(g['pending_upper_bound_usd']) + row.reserved_cost)
        if row.latency_ms is not None: g['latencies_ms'].append(row.latency_ms)
        if row.first_token_ms is not None: g['first_token_ms'].append(row.first_token_ms)
    for g in groups.values():
        g['success_rate'] = g['successes'] / g['requests']
        g['timeout_rate'] = g['timeouts'] / g['requests']
        g['error_rate'] = g['errors'] / g['requests']
    return envelope({'models': list(groups.values()), 'window': 'latest_2000_attempts', 'cost_type': 'estimates_not_supplier_invoice'})


@router.post('/chat', response_model=ApiResponse, status_code=202)
async def chat(body: TaskCreate, request: Request, idempotency_key: UUID = Header(alias='Idempotency-Key'), tenant=Depends(require_admin)):
    if body.workflow != 'chat':
        raise AppError('CHAT_WORKFLOW_REQUIRED', 'Chat must use the chat workflow', 422)
    return envelope(await TaskService(request.app.state.connections, request.app.state.settings).create(tenant, idempotency_key, body))


@router.get('/chat/history', response_model=ApiResponse)
async def history(request: Request, tenant=Depends(require_admin)):
    rows = await TaskService(request.app.state.connections, request.app.state.settings).list(tenant)
    return envelope([row for row in rows if row['options'].get('workflow') == 'chat'])
