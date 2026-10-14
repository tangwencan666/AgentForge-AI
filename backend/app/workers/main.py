import asyncio
import os
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.repositories.connections import Connections
from app.workers.engine import Worker


async def main():
    settings = get_settings()
    connections = Connections(settings)
    logger = configure_logging()
    try:
        logger.info("application_started")
        await Worker(connections, settings).run()
    finally:
        await connections.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        configure_logging().error("request_failed", extra={"error_type":type(exc).__name__})
        raise SystemExit(1) from None
