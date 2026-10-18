"""Fixed project migrations under maintenance permission and independent approval."""
from pathlib import Path
import sys
from maintenance_policy import cli_gate, maintenance_operation
cli_gate(__file__, __name__)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    action = arguments[0] if arguments else "upgrade"
    if len(arguments) > 1 or action not in {"upgrade", "check", "current"}:
        raise SystemExit("Allowed migration actions: upgrade, check, current")
    root = Path(__file__).resolve().parents[1]
    with maintenance_operation(root, "migrate." + action):
        from alembic import command
        from alembic.config import Config
        config = Config(str(root / "backend/alembic.ini"))
        try:
            if action == "upgrade":
                command.upgrade(config, "head")
            elif action == "check":
                command.check(config)
            else:
                command.current(config)
        except Exception as exc:
            print("Migration failed (" + type(exc).__name__ + "); secret values omitted", file=sys.stderr)
            return 1
    print("Migration " + action + " completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
