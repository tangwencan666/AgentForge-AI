from typing import Protocol


class SchedulerPort(Protocol):
    """P2 port only. P1 supplies no implementation and never queues tasks."""
    async def enqueue(self, task_id: str, tenant_id: str) -> None: ...
