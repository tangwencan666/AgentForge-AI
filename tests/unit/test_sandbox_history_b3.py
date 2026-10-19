from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.sandbox.history import replay_hold, review_metadata
from app.sandbox.daemon_isolation import DaemonObservation, independent_candidates


def execution(**updates):
    return SimpleNamespace(id=uuid4(),task_id=uuid4(),status='queued',cleanup_status='not_created',
        launch_claimed_at=None,container_id=None,**updates)


@pytest.mark.parametrize('status,cid',[('needs_reconciliation','a'*64),('failed',None),('succeeded','a'*64)])
def test_legacy_launched_history_cannot_replay_even_if_status_terminal(status,cid):
    row=execution();row.status=status;row.container_id=cid;row.launch_claimed_at=datetime.now(timezone.utc)
    before=vars(row).copy();result=review_metadata(row)
    assert not result['replay_allowed'] and result['disposition']=='QUARANTINED_NO_REPLAY'
    assert result['missing_evidence'] and not result['cleanup_authorized']
    assert vars(row)==before


@pytest.mark.parametrize('state',['UNKNOWN','CREATE_COMMITTED','CLEANUP_INTENT'])
def test_new_unknown_boundary_is_also_held(state):
    row=execution();owned=SimpleNamespace(execution_id=row.id,task_id=row.task_id,state=state)
    assert replay_hold(row,owned)=='EXTERNAL_BOUNDARY_UNRESOLVED'


def test_new_unlaunched_request_does_not_get_historical_outcome():
    assert replay_hold(execution()) is None
    assert replay_hold(None)=='EXECUTION_UNVERIFIED'


def test_label_or_client_flag_does_not_create_ownership(monkeypatch):
    row=execution();row.launch_claimed_at=datetime.now(timezone.utc)
    monkeypatch.setenv('AGENTFORGE_HISTORY_RESOLVED','true')
    row.labels={'owner':'trusted'}
    assert replay_hold(row)=='LEGACY_LAUNCH_UNOWNED'


def test_mismatched_task_ownership_is_rejected():
    row=execution();owned=SimpleNamespace(execution_id=row.id,task_id=uuid4(),state='CREATED')
    assert replay_hold(row,owned)=='OWNERSHIP_MISMATCH'


@pytest.mark.parametrize('other',[
    DaemonObservation('alias','other-pipe','main','linux'),
    DaemonObservation('unreachable','other-pipe',None,None),
    DaemonObservation('windows','other-pipe','different','windows'),
    DaemonObservation('changed','main-pipe','different','linux')])
def test_context_name_or_pipe_alone_cannot_prove_separate_daemon(other):
    result=independent_candidates(DaemonObservation('main','main-pipe','main','linux'),[other])
    assert result['status']=='BLOCKED' and not result['runner_start_authorized']


def test_distinct_daemon_is_only_candidate_not_permission_to_start_runner():
    result=independent_candidates(DaemonObservation('main','main-pipe','main','linux'),[
        DaemonObservation('test','test-pipe','different','linux')])
    assert result['status']=='PARTIAL' and result['candidates']==['test']
    assert not result['runner_start_authorized']
