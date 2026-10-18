"""Generate distinct project-local P4 credentials without displaying their values."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

@maintenance_action('bootstrap.p4')
def main():
    from pathlib import Path
    import secrets
    from dotenv import dotenv_values

    root = Path(__file__).resolve().parents[1]
    path = root / ".env"
    if not path.is_file():
        raise SystemExit("Run project bootstrap first")
    values = dotenv_values(path)
    additions = []
    for name in ("AGENTFORGE_MCP_SERVER_TOKEN", "AGENTFORGE_CAPABILITY_APPROVER_TOKEN"):
        if not values.get(name):
            additions.append(name + "=" + secrets.token_hex(32))
    if additions:
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n" + "\n".join(additions) + "\n")
    print("P4 credentials configured in ignored project .env; values were not printed")


if __name__ == "__main__":
    main()
