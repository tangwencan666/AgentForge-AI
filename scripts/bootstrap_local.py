"""Generate project-only development secrets without printing their values."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

@maintenance_action('bootstrap.local')
def main():
    from pathlib import Path
    import secrets

    root = Path(__file__).resolve().parents[1]
    env = root / ".env"
    if env.exists():
        raise SystemExit("Existing .env preserved; no overwrite performed")
    redis_config = root / "work" / "redis.conf"
    if redis_config.exists():
        raise SystemExit("Existing Redis config preserved; no overwrite performed")
    redis_config.parent.mkdir(parents=True, exist_ok=True)
    pg, pg_admin, redis, admin = (secrets.token_hex(32) for _ in range(4))
    content = f"""COMPOSE_PROJECT_NAME=agentforge-p1
    POSTGRES_PORT=15432
    REDIS_PORT=16379
    BACKEND_PORT=18100
    FRONTEND_PORT=15173
    POSTGRES_PASSWORD={pg_admin}
    APP_DB_PASSWORD={pg}
    REDIS_PASSWORD={redis}
    AGENTFORGE_ENVIRONMENT=development
    AGENTFORGE_DATABASE_URL=postgresql+asyncpg://agentforge:{pg}@127.0.0.1:15432/agentforge
    AGENTFORGE_REDIS_URL=redis://:{redis}@127.0.0.1:16379/0
    AGENTFORGE_ADMIN_TOKEN={admin}
    AGENTFORGE_TENANT_ID=00000000-0000-4000-8000-000000000001
    AGENTFORGE_ALLOWED_MODEL_HOSTS=api.openai.com,api.anthropic.com,generativelanguage.googleapis.com
    """
    with env.open("x", encoding="utf-8") as output:
        output.write(content)
    with redis_config.open("x", encoding="utf-8") as output:
        output.write(f"bind 0.0.0.0\nprotected-mode yes\nappendonly yes\nrequirepass {redis}\n")
    print("Created project .env and work/redis.conf; secret values omitted")


if __name__ == "__main__":
    main()
