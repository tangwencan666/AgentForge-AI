"""Separate bounded real-API acceptance. No credential => BLOCKED, never a Stub pass."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4
from app.core.config import Settings
from app.core.errors import AppError
from app.repositories.connections import Connections
from app.schemas.tasks import TaskCreate
from app.services.models import list_slots
from app.providers.router import resolve_credential
from app.services.tasks import TaskService, TERMINAL

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--roles', default='planner', choices=['planner', 'coder', 'researcher', 'reviewer', 'all'])
args = parser.parse_args()


async def run():
    s = Settings()
    result = {'status': 'BLOCKED', 'actual_calls': 0, 'results': [], 'reason': None}
    if not s.real_calls_enabled or s.real_test_budget_usd <= 0 or s.real_daily_budget_usd <= 0:
        result['reason'] = 'SERVER_REAL_CALLS_AND_APPROVED_TEST_QUOTA_REQUIRED'
        return result
    c = Connections(s)
    try:
        async with c.sessions() as session: slots = await list_slots(session, s.tenant_id)
        roles = ['planner','coder','researcher','reviewer'] if args.roles == 'all' else [args.roles]
        if len(roles) > s.real_test_max_calls:
            result['reason'] = 'REQUESTED_ROLES_EXCEED_APPROVED_TEST_CALL_COUNT'
            return result
        for slot in slots:
            if slot['role'] in roles: resolve_credential(slot['credential_reference'], s)
        service = TaskService(c, s)
        for role in roles:
            task = await service.create(s.tenant_id, uuid4(), TaskCreate(goal='Reply with the word connected.', execution_mode='real',
                workflow='chat', chat_role=role, require_approval=False, max_calls=1, max_iterations=1,
                timeout_seconds=60, max_budget_usd=min(s.real_test_budget_usd, 1)), model_test=True)
            # Use the real background Worker, not an in-process provider replacement.
            for _ in range(240):
                task = await service.get(UUID(task['task_id']), s.tenant_id)
                if task['status'] in TERMINAL: break
                await asyncio.sleep(.25)
            result['actual_calls'] += task['usage']['model_attempts']
            result['results'].append({'role': role, 'task_id': task['task_id'], 'status': task['status'],
                'usage': task['usage'], 'error_code': task['error_code']})
            if task['status'] != 'succeeded':
                result['status'], result['reason'] = 'FAILED', 'REAL_PROVIDER_TEST_DID_NOT_SUCCEED'
                return result
        result['status'], result['reason'] = 'PASSED', None
        return result
    except AppError as exc:
        result['reason'] = exc.code
        return result
    finally:
        await c.close()

try:
    preflight = Settings()
    if not preflight.real_calls_enabled or preflight.real_test_budget_usd <= 0 or preflight.real_daily_budget_usd <= 0:
        record = {'status': 'BLOCKED', 'actual_calls': 0, 'results': [], 'reason': 'SERVER_REAL_CALLS_AND_APPROVED_TEST_QUOTA_REQUIRED'}
    else:
        record = asyncio.run(run())
except Exception as exc:
    record = {'status': 'BLOCKED', 'actual_calls': 0, 'reason': type(exc).__name__}
(root / 'work').mkdir(exist_ok=True)
(root / 'work/p5-real-api.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
print(json.dumps(record))
raise SystemExit(0 if record['status'] == 'PASSED' else 2)
