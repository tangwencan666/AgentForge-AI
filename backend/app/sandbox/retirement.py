"""Pure offline retirement checklist evaluator. It grants NO runtime authority.

Input observations must eventually be collected by a separately reviewed trusted
deployment boundary. Neither this function nor a JSON report stops a Runner,
writes compatibility clearance, or authorizes thaw. Docker SDK remains unused.
"""
from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class RetirementObservation:
    daemon_id: str
    container_id: str
    image_id: str
    started_at: str
    observed_at: float
    running: bool
    pid: int
    restart_policy: str
    active_executions: int
    unclassified_resources: int
    control_processes: int
    old_database_connections: int
    dispatch_windows: int
    restart_sources_reviewed: bool
    admission_closed: bool


def assess_retirement(first, second):
    reasons = []
    for item in (first, second):
        if (type(item) is not RetirementObservation or type(item.observed_at) not in (int, float)
                or not math.isfinite(item.observed_at)
                or any(type(getattr(item, name)) is not int or getattr(item, name)<0 for name in
                       ('pid','active_executions','unclassified_resources','control_processes','old_database_connections','dispatch_windows'))
                or any(type(getattr(item, name)) is not bool for name in ('running','restart_sources_reviewed','admission_closed'))
                or not isinstance(item.container_id, str) or not isinstance(item.image_id, str)
                or not re.fullmatch('[0-9a-f]{64}', item.container_id)
                or not re.fullmatch('sha256:[0-9a-f]{64}', item.image_id)):
            return {'offline_checklist': 'BLOCKED', 'reasons': ['OBSERVATION_UNTRUSTED'],
                    'deployment_authorized': False, 'physical_exit_proven': False}
    identity = ('daemon_id', 'container_id', 'image_id', 'started_at')
    if any(not getattr(first, k) or getattr(first, k) != getattr(second, k) for k in identity):
        reasons.append('TARGET_CHANGED')
    if second.observed_at-first.observed_at < 60:
        reasons.append('OBSERVATION_WINDOW_INSUFFICIENT')
    for item in (first, second):
        if item.running or item.pid != 0: reasons.append('OLD_PROCESS_NOT_EXITED')
        if item.restart_policy != 'no' or not item.restart_sources_reviewed: reasons.append('OLD_RESTART_PATH_OPEN')
        if not item.admission_closed: reasons.append('ADMISSION_NOT_CLOSED')
        if item.active_executions or item.dispatch_windows: reasons.append('EXECUTION_NOT_DRAINED')
        if item.control_processes or item.old_database_connections: reasons.append('CONTROL_PROCESS_UNRESOLVED')
        if item.unclassified_resources: reasons.append('RESOURCE_UNVERIFIED')
    return {'offline_checklist': 'BLOCKED' if reasons else 'SATISFIED',
            'reasons': sorted(set(reasons)), 'deployment_authorized': False, 'physical_exit_proven': False}
