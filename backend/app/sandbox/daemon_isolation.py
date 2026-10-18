"""Read-only daemon identity comparison; no context switch or Docker action."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DaemonObservation:
    context: str
    endpoint: str
    daemon_id: str | None
    operating_system: str | None


def independent_candidates(main, observations):
    if type(main) is not DaemonObservation or not main.daemon_id or not main.endpoint:
        return {'status': 'BLOCKED', 'reason': 'MAIN_DAEMON_UNVERIFIED', 'candidates': []}
    candidates=[]
    for row in observations:
        if (type(row) is DaemonObservation and row.daemon_id and row.operating_system == 'linux'
                and row.daemon_id != main.daemon_id and row.endpoint and row.endpoint != main.endpoint):
            candidates.append(row.context)
    return {'status': 'PARTIAL' if candidates else 'BLOCKED',
        'reason': 'TARGET_ATTESTATION_REQUIRED' if candidates else 'NO_INDEPENDENT_DAEMON_CONFIRMED',
        'candidates': sorted(set(candidates)), 'runner_start_authorized': False}
