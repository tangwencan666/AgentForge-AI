"""Async PostgreSQL checkpointer with task-level fencing and tenant scope."""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP
from app.domain.tasks import GraphCheckpoint, GraphWrite, AgentTask
from app.services.tasks import locked_task, check_lease
from app.core.errors import AppError


class PostgresTaskSaver(BaseCheckpointSaver):
    def __init__(self, connections, tenant_id: str, task_id: UUID, owner: str, fence: int):
        super().__init__()
        self.connections, self.tenant_id, self.task_id = connections, tenant_id, task_id
        self.owner, self.fence = owner, fence

    def key(self, config):
        item = config["configurable"]
        if UUID(item["thread_id"]) != self.task_id:
            raise AppError("CHECKPOINT_FORBIDDEN", "Invalid graph task scope", 403)
        return item.get("checkpoint_ns", ""), item.get("checkpoint_id")

    async def allowed(self, session):
        if not await session.scalar(select(AgentTask.id).where(AgentTask.id == self.task_id, AgentTask.tenant_id == UUID(self.tenant_id))):
            raise AppError("CHECKPOINT_FORBIDDEN", "Graph task is not authorized", 403)

    async def _tuple(self, session, row):
        writes = (await session.scalars(select(GraphWrite).where(GraphWrite.task_id == self.task_id,
            GraphWrite.namespace == row.namespace, GraphWrite.checkpoint_id == row.checkpoint_id).order_by(GraphWrite.write_task_id, GraphWrite.idx))).all()
        base = {"thread_id":str(self.task_id),"checkpoint_ns":row.namespace}
        return CheckpointTuple(config={"configurable":{**base,"checkpoint_id":row.checkpoint_id}},
            checkpoint=self.serde.loads_typed((row.data_type, row.data)), metadata=self.serde.loads_typed((row.meta_type, row.meta)),
            parent_config={"configurable":{**base,"checkpoint_id":row.parent_id}} if row.parent_id else None,
            pending_writes=[(w.write_task_id,w.channel,self.serde.loads_typed((w.data_type,w.data))) for w in writes])

    async def aget_tuple(self, config):
        namespace, checkpoint_id = self.key(config)
        async with self.connections.sessions() as session:
            await self.allowed(session)
            stmt = select(GraphCheckpoint).where(GraphCheckpoint.task_id == self.task_id, GraphCheckpoint.namespace == namespace)
            if checkpoint_id:
                stmt = stmt.where(GraphCheckpoint.checkpoint_id == checkpoint_id)
            row = (await session.scalars(stmt.order_by(GraphCheckpoint.checkpoint_id.desc()).limit(1))).one_or_none()
            return await self._tuple(session, row) if row else None

    async def alist(self, config, *, filter=None, before=None, limit=None):
        if limit == 0:
            return
        if config is None:
            raise AppError("CHECKPOINT_FORBIDDEN", "Task scope is required", 403)
        namespace, _ = self.key(config)
        async with self.connections.sessions() as session:
            await self.allowed(session)
            stmt = select(GraphCheckpoint).where(GraphCheckpoint.task_id == self.task_id, GraphCheckpoint.namespace == namespace)
            if before:
                stmt = stmt.where(GraphCheckpoint.checkpoint_id < before["configurable"]["checkpoint_id"])
            rows = (await session.scalars(stmt.order_by(GraphCheckpoint.checkpoint_id.desc()))).all()
            count = 0
            for row in rows:
                result = await self._tuple(session, row)
                if filter and any(result.metadata.get(k) != v for k,v in filter.items()):
                    continue
                yield result
                count += 1
                if limit is not None and count >= limit:
                    break

    async def aput(self, config, checkpoint, metadata, new_versions):
        namespace, parent = self.key(config)
        data_type, data = self.serde.dumps_typed(checkpoint)
        meta_type, meta = self.serde.dumps_typed(metadata)
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, self.task_id, self.tenant_id)
            check_lease(task, self.owner, self.fence, allow_waiting=True)
            await session.execute(insert(GraphCheckpoint).values(task_id=self.task_id, namespace=namespace, checkpoint_id=checkpoint["id"],
                parent_id=parent, data_type=data_type, data=data, meta_type=meta_type, meta=meta).on_conflict_do_nothing())
        return {"configurable":{**config["configurable"],"checkpoint_ns":namespace,"checkpoint_id":checkpoint["id"]}}

    async def aput_writes(self, config, writes, task_id, task_path=""):
        namespace, checkpoint_id = self.key(config)
        if not checkpoint_id:
            raise AppError("CHECKPOINT_MISSING", "Write requires a durable checkpoint", 409)
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, self.task_id, self.tenant_id)
            check_lease(task, self.owner, self.fence, allow_waiting=True)
            for index, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, index)
                data_type, data = self.serde.dumps_typed(value)
                stmt = insert(GraphWrite).values(task_id=self.task_id, namespace=namespace, checkpoint_id=checkpoint_id,
                    write_task_id=task_id, idx=idx, channel=channel, data_type=data_type, data=data)
                if idx < 0:
                    stmt = stmt.on_conflict_do_update(index_elements=[GraphWrite.task_id,GraphWrite.namespace,GraphWrite.checkpoint_id,GraphWrite.write_task_id,GraphWrite.idx],
                        set_={"channel":channel,"data_type":data_type,"data":data})
                else:
                    stmt = stmt.on_conflict_do_nothing()
                await session.execute(stmt)
