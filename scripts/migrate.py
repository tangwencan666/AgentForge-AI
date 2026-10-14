"""Safe CLI boundary: never emit connection URLs or driver exception values."""
from pathlib import Path
import sys
from alembic import command
from alembic.config import Config

root = Path(__file__).resolve().parents[1]
config = Config(str(root / "backend" / "alembic.ini"))
action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
if action not in {"upgrade", "check", "current"}:
    raise SystemExit("Allowed migration actions: upgrade, check, current")
try:
    if action == "upgrade":
        command.upgrade(config, "head")
    elif action == "check":
        command.check(config)
    else:
        command.current(config)
except Exception as exc:
    print(f"Migration failed ({type(exc).__name__}); inspect project configuration and dependency status without logging secrets", file=sys.stderr)
    raise SystemExit(1) from None
print(f"Migration {action} completed")
