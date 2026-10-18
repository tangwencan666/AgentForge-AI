"""Disabled historical recovery entry point; no services or credentials are accessed.

The legacy P3 probe launches a default-queue Worker and cannot prove instance isolation.
Historical reports remain evidence of their original runs, not permission to restart
an existing main, Coder or maintenance instance today. This command has no override.
"""
import sys


def main() -> int:
    print(
        "LEGACY_RECOVERY_PROBE_DISABLED: this probe cannot safely isolate its instance, "
        "database and queue. No process was started, stopped or restarted. "
        "Use separately reviewed lifecycle-managed test fixtures.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
