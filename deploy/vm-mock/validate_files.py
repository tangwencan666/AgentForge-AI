"""Local static preparation checks. Never contacts an Engine or any service."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DEMO = Path(__file__).resolve().parent


def main():
    for path in DEMO.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # All interpolation values are disposable NON-SECRET parser fixtures.
    fixture = {
        "VM_MOCK_INSTANCE_ID": "STATIC_PARSE_ONLY_NOT_A_UUID",
        "VM_MOCK_APP_PASSWORD": "1" * 64,
        "VM_MOCK_REDIS_PASSWORD": "2" * 64,
        "VM_MOCK_ADMIN_TOKEN": "3" * 64,
        "VM_MOCK_POSTGRES_PASSWORD": "4" * 64,
        "VM_MOCK_BACKEND_IMAGE": "ghcr.io/static-fixture/backend@sha256:" + "0" * 64,
        "VM_MOCK_FRONTEND_IMAGE": "ghcr.io/static-fixture/frontend@sha256:" + "1" * 64,
    }
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(("COMPOSE_", "DOCKER_", "AGENTFORGE_", "VM_MOCK_", "BASH_"))}
    environment["COMPOSE_DISABLE_ENV_FILE"] = "1"
    # An accidental Engine query must fail instead of reaching Docker Desktop.
    endpoint = ("npipe:////./pipe/agentforge-static-no-engine" if os.name == "nt"
                else "unix:///nonexistent/agentforge-static-no-engine.sock")
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker Compose CLI required for static parsing only")
    command = [docker, "--host", endpoint, "compose"]
    version = subprocess.check_output(command + ["version", "--short"],
                                      env=environment, text=True, timeout=30).strip()
    descriptor, filename = tempfile.mkstemp(prefix="agentforge-static-", suffix=".inputs")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write("\n".join(key + "=" + value for key, value in fixture.items()) + "\n")
        result = subprocess.run(
            command + ["--env-file", filename, "--project-directory", str(DEMO),
                       "-f", str(DEMO / "compose.yaml"), "--profile", "data",
                       "--profile", "migration", "--profile", "app", "config", "--format", "json"],
            cwd=DEMO, env=environment, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError("Compose static parsing failed: " + result.stderr)
        config = json.loads(result.stdout)
    finally:
        Path(filename).unlink(missing_ok=True)
    services = config["services"]
    assert set(services) == {"postgres", "redis", "migrate", "backend", "worker", "frontend"}
    assert all(not service.get("ports") and not service.get("build")
               and not service.get("privileged") and not service.get("network_mode")
               and service["read_only"] for service in services.values())
    assert all(network["internal"] and not network.get("external")
               for network in config["networks"].values())
    assert all(not volume.get("external") for volume in config["volumes"].values())
    report = {"result": "STATIC_PREPARATION_PASS", "compose_cli": version,
              "services": sorted(services), "published_ports": 0, "engine_contact": False,
              "fixture_credentials_only": True, "app_images": "NOT_BUILT",
              "vm_runtime_compatibility": "NOT_TESTED"}
    destination = ROOT / "work/vm-mock-prep"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "static-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
