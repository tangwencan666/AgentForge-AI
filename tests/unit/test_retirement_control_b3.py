from dataclasses import replace
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4
import pytest
from app.sandbox.retirement_control import (OfflineRetirementController, ControlRefused, ALLOWED_ROOT)
from retirement_boundary import Boundary, TARGET, OPERATOR, APPROVER


@pytest.fixture
def control():
    directory=ALLOWED_ROOT/'offline-tests'/uuid4().hex
    port=Boundary(directory)
    manager=OfflineRetirementController(directory,TARGET,port,OPERATOR,APPROVER)
    return manager,port


def step(manager, port, action):
    port.actor=APPROVER; grant=manager.issue(action);port.actor=OPERATOR
    return manager.execute(grant)


def stopped(control):
    manager,port=control
    for action in ('SEAL_ADMISSION','DISABLE_RESTART','STOP_OLD'): step(manager,port,action)
    return manager,port


def test_complete_control_chain_never_grants_runtime_authority(control):
    manager,port=stopped(control)
    result=step(manager,port,'CHECK_EXIT')
    assert result['stage']=='EXIT_CHECKED_OFFLINE'
    assert not result['deployment_authorized'] and not result['physical_exit_proven']
    assert not result['new_runner_start_authorized']


@pytest.mark.parametrize('action',['STOP_OLD','CHECK_EXIT','DISABLE_RESTART','START_NEW','FORCE','RESTORE'])
def test_action_order_and_no_general_bypass(control,action):
    manager,_=control
    with pytest.raises(ControlRefused):manager.issue(action)


def test_client_cannot_choose_operator_identity(control,monkeypatch):
    manager,port=control;grant=manager.issue('SEAL_ADMISSION')
    monkeypatch.setenv('AGENTFORGE_WORKER_ID','trusted')
    monkeypatch.setenv('AGENTFORGE_SKIP_GUARD','true')
    port.actor=replace(OPERATOR,created=999)
    with pytest.raises(ControlRefused,match='OPERATOR_IDENTITY_REQUIRED'):manager.execute(grant)
    assert not port.effects


def test_expired_grant_has_no_effect(control):
    manager,port=control;manager.clock=lambda:100;grant=manager.issue('SEAL_ADMISSION',ttl=1)
    port.actor=OPERATOR;manager.clock=lambda:102
    with pytest.raises(ControlRefused,match='GRANT_REFUSED'):manager.execute(grant)
    assert not port.effects


def test_target_generation_changes_refuse_existing_journal(control):
    manager,port=control
    with pytest.raises(ControlRefused,match='CONTROL_TARGET_CHANGED'):
        OfflineRetirementController(manager.directory,replace(TARGET,generation=2),port,OPERATOR,APPROVER)


def test_replay_and_old_epoch_refused(control):
    manager,port=control;g1=manager.issue('SEAL_ADMISSION');g2=manager.issue('SEAL_ADMISSION')
    port.actor=OPERATOR;manager.execute(g1)
    for grant in (g1,g2):
        with pytest.raises(ControlRefused):manager.execute(grant)
    assert port.effects==['SEAL_ADMISSION']


@pytest.mark.parametrize('overrides',[{'dispatch_windows':1},{'active_executions':1},
    {'unknown_resources':1},{'history_replay_blocked':False},{'admission_sealed':False}])
def test_unresolved_boundary_prevents_stop_without_mutation(control,overrides):
    manager,port=control;step(manager,port,'SEAL_ADMISSION');step(manager,port,'DISABLE_RESTART')
    port.actor=APPROVER;grant=manager.issue('STOP_OLD');port.actor=OPERATOR;port.overrides=overrides
    with pytest.raises(ControlRefused):manager.execute(grant)
    assert 'STOP_OLD' not in port.effects


def test_restart_risk_after_intent_is_unknown_and_never_reissued(control):
    manager,port=control;step(manager,port,'SEAL_ADMISSION');step(manager,port,'DISABLE_RESTART')
    port.actor=APPROVER;grant=manager.issue('STOP_OLD');port.actor=OPERATOR;port.closed=False
    with pytest.raises(ControlRefused,match='ACTION_UNKNOWN_NO_REPLAY'):manager.execute(grant)
    assert manager.recover()['stage']=='RECOVERY_REQUIRED'
    port.actor=APPROVER
    with pytest.raises(ControlRefused):manager.issue('STOP_OLD')
    assert port.running


def test_private_error_never_written_and_unknown_retained(control):
    manager,port=control;port.fail='SEAL_ADMISSION'
    with pytest.raises(ControlRefused,match='ACTION_UNKNOWN_NO_REPLAY'):step(manager,port,'SEAL_ADMISSION')
    assert manager.stage()=='RECOVERY_REQUIRED'
    assert b'synthetic-private-value' not in manager.database.read_bytes()
    assert manager.recover()['admission_open'] is False


def test_cleanup_loop_or_inflight_request_prevents_clearance(control):
    manager,port=stopped(control);port.overrides={'cleanup_loop_exited':False,'inflight_docker':1}
    with pytest.raises(ControlRefused):step(manager,port,'CHECK_EXIT')
    assert manager.stage()=='RECOVERY_REQUIRED'


def test_false_or_changed_target_cannot_seal_wrong_instance(control):
    manager,port=control;grant=manager.issue('SEAL_ADMISSION');port.actor=OPERATOR
    port.target=replace(TARGET,container_id='c'*64)
    with pytest.raises(ControlRefused):manager.execute(grant)
    assert not port.effects


def child(manager, grant, mode):
    # The child inherits OS runtime variables ONLY. No model/issuer values read.
    root=Path(__file__).resolve().parents[2]
    env={n:os.environ[n] for n in ('SystemRoot','WINDIR','PATH','PATHEXT','COMSPEC','TEMP','TMP','APPDATA','LOCALAPPDATA','USERPROFILE') if n in os.environ}
    env.update(PYTHONPATH=os.pathsep.join(str(root/n) for n in ('backend','tests/fixtures')),
        PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    return subprocess.Popen([sys.executable,'-B',str(root/'tests/fixtures/retirement_control_worker.py'),
        str(manager.directory),grant,mode],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def test_real_process_competition_single_intent_and_single_stub_effect(control):
    manager,port=control;step(manager,port,'SEAL_ADMISSION');step(manager,port,'DISABLE_RESTART')
    port.actor=APPROVER;grant=manager.issue('STOP_OLD')
    processes=[child(manager,grant,'execute') for _ in range(2)]
    try: assert sorted(p.wait(timeout=12) for p in processes)==[0,2]
    finally:
        for p in processes:
            if p.poll() is None:p.terminate();p.wait(timeout=5)  # Only held child handles.
    assert (manager.directory/'stub-effects.jsonl').read_text().splitlines().count('STOP_OLD')==1


def test_real_child_crash_after_intent_never_replays(control):
    manager,port=control;step(manager,port,'SEAL_ADMISSION');step(manager,port,'DISABLE_RESTART')
    port.actor=APPROVER;grant=manager.issue('STOP_OLD');process=child(manager,grant,'crash')
    try: assert process.wait(timeout=12)==51
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=5)
    restored=OfflineRetirementController(manager.directory,TARGET,port,OPERATOR,APPROVER)
    assert restored.recover()['stage']=='RECOVERY_REQUIRED'
    port.actor=OPERATOR
    with pytest.raises(ControlRefused):restored.execute(grant)
    assert (manager.directory/'stub-effects.jsonl').read_text().splitlines().count('STOP_OLD')==1


def test_journal_cannot_be_main_lifecycle_directory(control):
    manager,port=control
    with pytest.raises(ControlRefused,match='OFFLINE_SCOPE_REQUIRED'):
        OfflineRetirementController(ALLOWED_ROOT.parent.parent/'lifecycle',TARGET,port,OPERATOR,APPROVER)


@pytest.mark.parametrize('overrides',[{'dispatch_windows':False},{'unknown_resources':-1},
    {'pid':'0'},{'admission_sealed':'true'},{'inflight_docker':float('nan')}])
def test_malformed_observation_is_not_boolean_authority(control,overrides):
    manager,port=control;port.overrides=overrides
    with pytest.raises(ControlRefused):step(manager,port,'SEAL_ADMISSION')
    assert manager.stage()=='RECOVERY_REQUIRED'


def test_path_traversal_cannot_escape_offline_root(control):
    manager,port=control
    with pytest.raises(ControlRefused,match='OFFLINE_SCOPE_REQUIRED'):
        OfflineRetirementController(ALLOWED_ROOT/'unused'/Path('../../../lifecycle'),TARGET,port,OPERATOR,APPROVER)
