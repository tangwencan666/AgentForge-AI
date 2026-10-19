"""Isolated controller Stub. No Docker, subprocess commands or real credentials."""
from dataclasses import replace
import os
from pathlib import Path
from uuid import UUID
from app.sandbox.retirement import RetirementObservation
from app.sandbox.retirement_control import OfflineBoundary, Peer, Target

OPERATOR=Peer('S-1-5-21-100',100,1000,'C:/stub/operator.exe')
APPROVER=Peer('S-1-5-21-200',200,2000,'C:/stub/approver.exe')
TARGET=Target(UUID(int=1),UUID(int=2),1,'stub-daemon','a'*64,'sha256:'+'b'*64,'2026-10-18T00:00:00Z')


class Boundary(OfflineBoundary):
    def __init__(self, directory=None):
        self.actor=APPROVER; self.target=TARGET; self.sealed=False;self.running=True
        self.restart='unless-stopped'; self.closed=False; self.fail=None; self.effects=[]
        self.directory=Path(directory) if directory else None
        self.overrides={}; self.crash=False
    def peer(self): return self.actor
    def observe(self):
        return {'target':self.target,'admission_sealed':self.sealed,'dispatch_windows':0,
            'active_executions':0,'unknown_resources':0,'history_replay_blocked':True,
            'restart_policy':self.restart,'restart_sources_closed':self.closed,
            'running':self.running,'pid':123 if self.running else 0,
            'cleanup_loop_exited':not self.running,'inflight_docker':0,**self.overrides}
    def effect(self, action):
        self.effects.append(action)
        if self.directory:
            with (self.directory/'stub-effects.jsonl').open('a',encoding='utf-8') as f:f.write(action+'\n')
        if self.crash:os._exit(51)
        if self.fail==action: raise OSError('synthetic-private-value-not-to-be-logged')
    def seal_admission(self):self.effect('SEAL_ADMISSION');self.sealed=True;return True
    def disable_restart(self, target):self.effect('DISABLE_RESTART');self.restart='no';self.closed=True
    def stop_old(self, target):self.effect('STOP_OLD');self.running=False
    def exit_samples(self):
        first=RetirementObservation(self.target.daemon_id,self.target.container_id,self.target.image_id,
            self.target.started_at,0,self.running,123 if self.running else 0,self.restart,0,0,0,0,0,self.closed,self.sealed)
        return first,replace(first,observed_at=61)
