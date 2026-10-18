"""Finite retirement control kernel, available ONLY to isolated offline ports.

No Docker/HTTP/shell adapter, production CLI, clearance writer or thaw entry is
provided. The kernel persists single-use intents before calling a test boundary.
A production port and authenticated proof delivery require separate acceptance.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from uuid import UUID, uuid4

from app.sandbox.retirement import assess_retirement

ROOT = Path(__file__).resolve().parents[3]
ALLOWED_ROOT = ROOT / 'work' / 'maint-s3b3'
STEPS = {'SEAL_ADMISSION': ('FROZEN', 'ADMISSION_SEALED'),
         'DISABLE_RESTART': ('ADMISSION_SEALED', 'RESTART_DISABLED'),
         'STOP_OLD': ('RESTART_DISABLED', 'STOPPED_PENDING_PROOF'),
         'CHECK_EXIT': ('STOPPED_PENDING_PROOF', 'EXIT_CHECKED_OFFLINE')}


class ControlRefused(RuntimeError):
    pass


def require(value, code='RETIREMENT_CONTROL_REFUSED'):
    if not value:
        raise ControlRefused(code)


@dataclass(frozen=True)
class Target:
    project_id: UUID
    runner_instance_id: UUID
    generation: int
    daemon_id: str
    container_id: str
    image_id: str
    started_at: str

    def key(self):
        require(type(self.project_id) is UUID and type(self.runner_instance_id) is UUID
                and type(self.generation) is int and self.generation > 0
                and isinstance(self.daemon_id, str) and 0 < len(self.daemon_id) <= 128
                and isinstance(self.container_id, str) and re.fullmatch('[0-9a-f]{64}', self.container_id)
                and isinstance(self.image_id, str) and re.fullmatch('sha256:[0-9a-f]{64}', self.image_id)
                and isinstance(self.started_at, str) and 0 < len(self.started_at) <= 64)
        return hashlib.sha256(json.dumps(asdict(self), default=str, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Peer:
    """Obtained from the boundary's authenticated peer, never a request worker_id."""
    user_sid: str
    process_id: int
    created: int
    executable: str

    def key(self):
        require(isinstance(self.user_sid, str) and self.user_sid.startswith('S-1-')
                and type(self.process_id) is int and self.process_id > 0
                and type(self.created) is int and self.created > 0
                and isinstance(self.executable, str) and bool(self.executable))
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


class OfflineBoundary:
    """Explicit Stub port. No production implementation is shipped in this phase."""
    def peer(self): raise NotImplementedError
    def observe(self): raise NotImplementedError
    def seal_admission(self): raise NotImplementedError
    def disable_restart(self, target): raise NotImplementedError
    def stop_old(self, target): raise NotImplementedError
    def exit_samples(self): raise NotImplementedError


@contextmanager
def exclusive_file(path):
    """OS lock remains held through final target verification and bounded IO."""
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == 'nt':
            import msvcrt
            try: msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError: raise ControlRefused('CONTROL_BUSY') from None
        else:
            import fcntl
            try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError: raise ControlRefused('CONTROL_BUSY') from None
        yield
    finally:
        os.close(descriptor)  # OS releases lock even on failed/unknown actions.


class OfflineRetirementController:
    def __init__(self, directory, target, boundary, operator, approver, *, clock=time.time):
        require(isinstance(boundary, OfflineBoundary), 'OFFLINE_BOUNDARY_REQUIRED')
        path = Path(directory).absolute()
        require(path.is_relative_to(ALLOWED_ROOT) and path != ALLOWED_ROOT, 'OFFLINE_SCOPE_REQUIRED')
        for p in (path, *path.parents):
            if p.exists():
                info = p.lstat()
                require(not p.is_symlink() and not getattr(info, 'st_file_attributes', 0) & 0x400, 'CONTROL_PATH_UNTRUSTED')
        path=path.resolve()
        require(path.is_relative_to(ALLOWED_ROOT.resolve()) and path!=ALLOWED_ROOT.resolve(), 'OFFLINE_SCOPE_REQUIRED')
        path.mkdir(parents=True, exist_ok=True)
        self.directory, self.target, self.boundary, self.clock = path, target, boundary, clock
        self.operator, self.approver = operator.key(), approver.key()
        require(self.operator != self.approver, 'TWO_PRINCIPALS_REQUIRED')
        self.binding = target.key()
        self.database = path / 'offline-control.sqlite3'
        for p in (self.database, path/'control.lock'):
            if p.exists(): require(not p.is_symlink() and not getattr(p.lstat(), 'st_file_attributes', 0) & 0x400)
        with exclusive_file(path/'control.lock'), self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT NOT NULL, operator TEXT NOT NULL, approver TEXT NOT NULL, epoch INTEGER NOT NULL, stage TEXT NOT NULL);'
                'CREATE TABLE IF NOT EXISTS grants (id TEXT PRIMARY KEY, action TEXT NOT NULL, binding TEXT NOT NULL, epoch INTEGER NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL);'
                'CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, action TEXT NOT NULL, result TEXT NOT NULL, grant_id TEXT, observed REAL NOT NULL);')
            row = db.execute('SELECT binding,operator,approver FROM state WHERE id=1').fetchone()
            if row:
                require(row == (self.binding,self.operator,self.approver), 'CONTROL_TARGET_CHANGED')
            else:
                db.execute('INSERT INTO state VALUES(1,?,?,?,1,?)', (self.binding,self.operator,self.approver,'FROZEN'))
                self.audit(db,'INSTALL','FROZEN',None)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.database, timeout=1)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db: yield db
        finally:
            db.close()

    def stamp(self):
        stamp=self.clock()
        require(type(stamp) in (int,float) and math.isfinite(stamp), 'CONTROL_CLOCK_UNTRUSTED')
        return stamp

    def audit(self, db, action, result, grant):
        db.execute('INSERT INTO audit(action,result,grant_id,observed) VALUES(?,?,?,?)', (action,result,grant,self.stamp()))

    def stage(self):
        with self.connect() as db:
            return db.execute('SELECT stage FROM state WHERE id=1').fetchone()[0]

    def issue(self, action, *, ttl=60):
        require(action in STEPS and type(ttl) is int and 0 < ttl <= 60)
        require(self.boundary.peer().key() == self.approver, 'APPROVER_IDENTITY_REQUIRED')
        with exclusive_file(self.directory/'control.lock'), self.connect() as db:
            row=db.execute('SELECT binding,epoch,stage FROM state WHERE id=1').fetchone()
            require(row[0]==self.binding and row[2]==STEPS[action][0], 'CONTROL_STAGE_REFUSED')
            grant=str(uuid4())
            db.execute('INSERT INTO grants VALUES(?,?,?,?,?,0)',(grant,action,self.binding,row[1],self.stamp()+ttl))
            self.audit(db,action,'ISSUED',grant)
            return grant

    def observe_bound(self):
        observation = self.boundary.observe()
        require(type(observation) is dict and observation.get('target') == self.target, 'CONTROL_TARGET_CHANGED')
        require(all(type(observation.get(name)) is int and observation[name]>=0 for name in
                    ('dispatch_windows','active_executions','unknown_resources','pid','inflight_docker'))
                and all(type(observation.get(name)) is bool for name in
                    ('admission_sealed','history_replay_blocked','restart_sources_closed','running','cleanup_loop_exited')),
                'CONTROL_OBSERVATION_UNTRUSTED')
        # These facts come from a Stub port, not from HTTP/CLI/JSON claims.
        require(observation.get('admission_sealed') is True and observation.get('dispatch_windows') == 0
                and observation.get('active_executions') == 0 and observation.get('unknown_resources') == 0
                and observation.get('history_replay_blocked') is True, 'RETIREMENT_NOT_DRAINED')
        return observation

    def execute(self, grant):
        require(type(grant) is str and len(grant)<=64)
        require(self.boundary.peer().key()==self.operator, 'OPERATOR_IDENTITY_REQUIRED')
        with exclusive_file(self.directory/'control.lock'):
            require(self.boundary.peer().key()==self.operator, 'OPERATOR_IDENTITY_REQUIRED')
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT action,binding,epoch,expires,used FROM grants WHERE id=?',(grant,)).fetchone()
                current=db.execute('SELECT binding,epoch,stage FROM state WHERE id=1').fetchone()
                require(row and not row[4] and row[1]==self.binding==current[0]
                        and row[2]==current[1] and row[3]>self.stamp() and current[2]==STEPS[row[0]][0], 'GRANT_REFUSED')
                action=row[0]
                # Revalidate before durable intent, then again immediately before IO.
                require(self.boundary.observe().get('target')==self.target, 'CONTROL_TARGET_CHANGED')
                if action != 'SEAL_ADMISSION': self.observe_bound()
                db.execute('UPDATE grants SET used=1 WHERE id=?',(grant,))
                db.execute('UPDATE state SET stage=? WHERE id=1',(action+'_COMMITTED',))
                self.audit(db,action,'INTENT_COMMITTED',grant)
            try:
                if action=='SEAL_ADMISSION':
                    require(self.boundary.seal_admission() is True)
                    self.observe_bound()
                else:
                    facts=self.observe_bound()
                    if action=='DISABLE_RESTART': self.boundary.disable_restart(self.target)
                    elif action=='STOP_OLD':
                        require(facts.get('restart_policy')=='no' and facts.get('restart_sources_closed') is True, 'RESTART_PATH_OPEN')
                        self.boundary.stop_old(self.target)
                    else:
                        first, second=self.boundary.exit_samples()
                        for item in (first,second):
                            require((item.daemon_id,item.container_id,item.image_id,item.started_at)==(
                                self.target.daemon_id,self.target.container_id,self.target.image_id,self.target.started_at))
                        require(assess_retirement(first,second)['offline_checklist']=='SATISFIED','EXIT_NOT_PROVEN')
                after=self.observe_bound()
                if action in {'DISABLE_RESTART','STOP_OLD','CHECK_EXIT'}:
                    require(after.get('restart_policy')=='no' and after.get('restart_sources_closed') is True, 'RESTART_PATH_OPEN')
                if action in {'STOP_OLD','CHECK_EXIT'}:
                    require(after.get('running') is False and after.get('pid')==0
                            and after.get('cleanup_loop_exited') is True and after.get('inflight_docker')==0, 'EXIT_NOT_PROVEN')
                with self.connect() as db:
                    db.execute('UPDATE state SET stage=?,epoch=epoch+1 WHERE id=1',(STEPS[action][1],))
                    self.audit(db,action,'OFFLINE_VERIFIED',grant)
            except BaseException:
                with self.connect() as db:
                    db.execute("UPDATE state SET stage='RECOVERY_REQUIRED',epoch=epoch+1 WHERE id=1")
                    self.audit(db,action,'UNKNOWN_NO_REPLAY',grant)
                raise ControlRefused('ACTION_UNKNOWN_NO_REPLAY') from None
        return {'stage':self.stage(),'mode':'OFFLINE_STUB', 'physical_exit_proven':False,
                'deployment_authorized':False,'new_runner_start_authorized':False}

    def recover(self):
        """A crash after intent consumes the grant forever. Recovery observes only."""
        with exclusive_file(self.directory/'control.lock'), self.connect() as db:
            stage=db.execute('SELECT stage FROM state WHERE id=1').fetchone()[0]
            if stage.endswith('_COMMITTED'):
                db.execute("UPDATE state SET stage='RECOVERY_REQUIRED',epoch=epoch+1 WHERE id=1")
                self.audit(db,'RECOVER','UNKNOWN_NO_REPLAY',None)
        return {'stage':self.stage(),'admission_open':False,'deployment_authorized':False}
