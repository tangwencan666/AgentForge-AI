"""Pause/restore ONLY this project's original idle Runner during clone regressions."""

from maintenance_policy import cli_gate, maintenance_action, authorize_maintenance_command
cli_gate(__file__, __name__)

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from sqlalchemy import select, func
from app.core.config import Settings, runtime_env_file
from app.domain.sandbox import SandboxExecution
from app.repositories.connections import Connections
from app.services.sandbox import EXECUTION_TERMINAL

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT/'work/p5-live-preflight/permit-test/original-runner-state.json'
NAME = 'agentforge-p3-runner'


def command(*args):
    authorize_maintenance_command("runner", args)
    result = subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode: raise RuntimeError('Project Runner ownership/action check failed')
    return result.stdout.strip()


@maintenance_action(lambda a, k: {"pause":"runner.pause","restore":"runner.restore"}.get(k.get("action", a[0] if a else ""), ""))
async def main(action):
    settings = Settings()
    assert runtime_env_file() == ROOT/'work/p5-live-preflight/.env'
    assert urlsplit(settings.database_url.get_secret_value()).port == 15432
    assert not settings.real_calls_enabled and not settings.single_use_permits_enabled
    assert command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}',NAME) == 'agentforge-p1'
    assert Path(command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project.working_dir"}}',NAME)).resolve() == ROOT
    if action == 'pause':
        c = Connections(settings)
        try:
            async with c.sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SandboxExecution).where(
                    SandboxExecution.status.not_in(EXECUTION_TERMINAL))) == 0
        finally: await c.close()
        if STATE.exists() and json.loads(STATE.read_text()).get('paused'):
            assert command('docker','inspect','--format','{{.State.Running}}',NAME) == 'false'
            print('Original project Runner already paused by this test harness')
            return
        was_running = command('docker','inspect','--format','{{.State.Running}}',NAME) == 'true'
        STATE.write_text(json.dumps({'name':NAME,'was_running':was_running,'paused':True}), encoding='utf-8')
        if was_running: command('docker','stop',NAME)
        print('Original project Runner paused; original active sandbox executions: 0')
    else:
        state = json.loads(STATE.read_text())
        assert state['name'] == NAME and state['paused']
        assert command('docker','inspect','--format','{{.State.Running}}','agentforge-permit-tests-runner') == 'false'
        assert not command('docker','ps','-aq','--filter','label=agentforge.sandbox.execution')
        if state['was_running']: command('docker','start',NAME)
        STATE.write_text(json.dumps(state | {'paused':False}), encoding='utf-8')
        print('Original project Runner restored to its previous running state')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['pause','restore'])
    try: asyncio.run(main(parser.parse_args().action))
    except Exception as exc:
        print('Runner test isolation failed: '+type(exc).__name__)
        raise SystemExit(1) from None
