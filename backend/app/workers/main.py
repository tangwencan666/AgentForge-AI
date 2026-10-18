import asyncio
import os
import sys
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
from app.core.config import Settings
from app.core.logging import configure_logging
from app.repositories.connections import Connections
from app.workers.engine import Worker


def load_worker_settings():
    # Issuance authority belongs to the API/operator, never the executing Worker.
    os.environ.pop('AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN', None)
    return Settings(model_permit_issuer_token=None)


async def main():
    settings = load_worker_settings()
    connections = Connections(settings)
    logger = configure_logging()
    from app.services.model_runtime_status import publish_worker_status
    status_task = asyncio.create_task(publish_worker_status(connections, settings))
    try:
        worker = Worker(connections, settings)
        lifecycle = sys.modules.get("lifecycle_runtime")
        if lifecycle is not None:
            # Initialization must succeed before the immutable instance reports
            # READY; it does not consume, publish or execute a task.
            await worker.initialize()
            lifecycle.ready("worker")
        logger.info("application_started")
        await worker.run()
    finally:
        status_task.cancel()
        await asyncio.gather(status_task, return_exceptions=True)
        await connections.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        configure_logging().error("request_failed", extra={"error_type":type(exc).__name__})
        raise SystemExit(1) from None
