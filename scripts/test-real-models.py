"""Observe ONE independently issued permit. Never issue, dispatch, retry or resolve keys."""
from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)
import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID
from app.core.config import Settings
from app.core.errors import AppError
from app.repositories.connections import Connections
from app.services.execution_permits import PermitService

ROOT = Path(__file__).resolve().parents[1]
@maintenance_action("model.observe")
async def run(permit_id=None):
    result = {'status': 'BLOCKED', 'actual_calls': 0, 'observes_only_no_dispatch': True,
              'reason': 'INDEPENDENT_SERVER_PERMIT_AND_FRESH_AUTHORIZATION_REQUIRED'}
    if permit_id is None: return result
    c = Connections(Settings())
    try:
        service = PermitService(c, c.settings)
        async with asyncio.timeout(60):
            while True:
                permit = await service.get(permit_id)
                if permit['status'] not in {'ISSUED','CLAIMED','DISPATCH_COMMITTED'}: break
                await asyncio.sleep(.25)
        # Durable dispatch intent is an upper bound, not proof that bytes reached the supplier.
        result.update(permit=permit, actual_calls=0 if not permit['dispatch_attempts'] else
            (1 if permit['http_status'] is not None else 'UNKNOWN'),
            dispatch_attempt_upper_bound=permit['dispatch_attempts'])
        result['status'] = 'PASS' if permit['status'] == 'SUCCEEDED' and permit['usage_status'] == 'reported_estimate' else 'PARTIAL'
        result['reason'] = permit['error_code'] or ('USAGE_UNKNOWN' if permit['usage_status'] == 'unknown' else None)
    except AppError as exc:
        result['reason'] = exc.code
        result['actual_calls'] = 'UNKNOWN'
    except TimeoutError:
        result.update(reason='OBSERVATION_TIMEOUT_NO_RETRY', actual_calls='UNKNOWN')
    finally:
        await c.close()
    return result


@maintenance_action("model.observe")
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--permit-id', type=UUID, help='Server-issued identifier; no client-specified roles, prompts or limits')
    args = parser.parse_args(argv)
    try:
        record = asyncio.run(run(args.permit_id))
    except Exception as exc:
        record = {'status': 'BLOCKED', 'actual_calls': 'UNKNOWN', 'observes_only_no_dispatch': True, 'reason': type(exc).__name__}
    (ROOT / 'work').mkdir(exist_ok=True)
    (ROOT / 'work/p5-real-api.json').write_text(json.dumps(record, indent=2, default=str), encoding='utf-8')
    print(json.dumps(record, default=str))
    return 0 if record['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
