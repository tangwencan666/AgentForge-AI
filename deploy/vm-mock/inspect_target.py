"""Read-only target/image preflight, also compatible with CentOS 7 Python 2.7.

It contains no create/start/pull/load/build/migrate operations.
"""
from __future__ import print_function
import json
import os
import re
import subprocess
import sys

EXPECTED_ENGINE = "f270beef-fc00-4691-8d57-a6643ad6f7cd"
KNOWN_CONTAINERS = {
    "ai-tianji-web-1", "ai-tianji-backend-1", "mysql8", "redis", "vigorous_hugle"
}
PREFIX = "agentforge-vm-mock-"
try:
    STRING_TYPES = (basestring,)
except NameError:
    STRING_TYPES = (str,)


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def docker(*arguments):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("DOCKER_")}
    result = subprocess.check_output(
        ["/usr/bin/docker", "--host", "unix:///run/docker.sock"] + list(arguments),
        env=environment, stderr=subprocess.PIPE)
    return result.decode("utf-8").strip()


def validate_image_lock(lock):
    require(lock.get("expected_engine_id") == EXPECTED_ENGINE, "VM_EXPECTED_ENGINE_LOCK_MISMATCH")
    require(lock.get("platform") == "linux/amd64", "VM_PLATFORM_LOCK_MISMATCH")
    require(lock.get("build_status") == "BUILT", "VM_APP_IMAGES_NOT_BUILT")
    for name in ("backend", "frontend"):
        artifact = lock["artifacts"][name]
        require(isinstance(artifact.get("reference"), STRING_TYPES)
                and re.match(r"^(?:[a-z0-9./:_-]+@)?sha256:[a-f0-9]{64}$", artifact["reference"]),
                "VM_IMMUTABLE_IMAGE_REFERENCE_REQUIRED")
        if artifact["reference"].startswith("sha256:"):
            require(artifact.get("config_digest") == artifact["reference"]
                    and artifact.get("image_id") == artifact["reference"], "VM_IMAGE_CONFIG_LOCK_MISMATCH")
        require(isinstance(artifact.get("build_revision"), STRING_TYPES)
                and re.match(r"^[a-f0-9]{40}$", artifact["build_revision"]),
                "VM_BUILD_REVISION_REQUIRED")


def inventory(call=docker):
    require(call("info", "--format", "{{.ID}}") == EXPECTED_ENGINE,
            "VM_WRONG_ENGINE")
    require(call("info", "--format", "{{.Swarm.LocalNodeState}}") == "inactive",
            "VM_SWARM_MUST_BE_INACTIVE")
    rows = []
    for identifier in call("ps", "-aq").split():
        row = json.loads(call(
            "inspect", "--type", "container", identifier, "--format",
            '{"name":{{json .Name}},"running":{{json .State.Running}},'
            '"status":{{json .State.Status}},"restart":{{json .HostConfig.RestartPolicy.Name}}}'))
        name = row["name"].lstrip("/")
        require(name in KNOWN_CONTAINERS, "VM_CONTAINER_INVENTORY_CHANGED")
        require(not row["running"] and row["status"] == "exited", "VM_EXISTING_WORKLOAD_RUNNING")
        require(row["restart"] == "no", "VM_EXISTING_RESTART_POLICY_CHANGED")
        rows.append({"name": name, "status": row["status"]})
    require({row["name"] for row in rows} == KNOWN_CONTAINERS, "VM_CONTAINER_INVENTORY_CHANGED")
    networks = call("network", "ls", "--format", "{{.Name}}").splitlines()
    volumes = call("volume", "ls", "--format", "{{.Name}}").splitlines()
    require(not any(name.startswith(PREFIX) for name in networks + volumes),
            "VM_DEMO_RESOURCE_ALREADY_EXISTS")
    require({"mysql-data", "redis-data"}.issubset(set(volumes)), "VM_PRESERVED_VOLUME_MISSING")
    # Do not rely on info's Running counter: it disagrees with per-container
    # states on this audited Engine after restoring stale historical state.
    return {"engine_id": EXPECTED_ENGINE, "containers": rows, "networks": networks,
            "volumes": volumes, "result": "READ_ONLY_PREFLIGHT"}


def images(lock, call=docker):
    validate_image_lock(lock)
    dependencies = lock.get("official_dependencies", {})
    references = {name: dependencies.get(name, {}).get("image_id", lock["bases"][name])
                  for name in ("postgres", "redis")}
    references.update({name: lock["artifacts"][name]["reference"]
                       for name in ("backend", "frontend")})
    for name, reference in references.items():
        row = json.loads(call(
            "image", "inspect", reference, "--format",
            '{"id":{{json .Id}},"digests":{{json .RepoDigests}},'
            '"architecture":{{json .Architecture}},"os":{{json .Os}},'
            '"labels":{{json .Config.Labels}}}'))
        require(row["architecture"] == "amd64" and row["os"] == "linux",
                "VM_IMAGE_PLATFORM_MISMATCH")
        if reference.startswith("sha256:"):
            require(row["id"] == reference, "VM_IMAGE_CONFIG_LOCK_MISMATCH")
        else:
            repository, digest = reference.split("@")
            prefix, separator, leaf = repository.rpartition("/")
            canonical = (prefix + separator if separator else "") + leaf.split(":")[0] + "@" + digest
            require(canonical in (row["digests"] or []), "VM_IMAGE_DIGEST_MISMATCH")
        if name in ("backend", "frontend"):
            labels = row["labels"] or {}
            require(labels.get("ai.agentforge.demo") == "vm-mock"
                    and labels.get("org.opencontainers.image.source")
                    == "https://github.com/tangwencan666/AgentForge-AI"
                    and labels.get("org.opencontainers.image.revision")
                    == lock["artifacts"][name]["build_revision"],
                    "VM_IMAGE_PROVENANCE_MISMATCH")


def main():
    require(sys.platform in ("linux", "linux2"), "VM_LINUX_HOST_REQUIRED")
    arguments = sys.argv[1:]
    require(arguments in ([], ["--images"]) or len(arguments) == 3
            and arguments[:2] == ["--images", "--manifest"], "VM_PREFLIGHT_ARGUMENTS")
    manifest = arguments[2] if len(arguments) == 3 else os.path.join(os.path.dirname(__file__), "images.lock.json")
    with open(manifest) as file:
        lock = json.load(file)
    if arguments:
        # An unresolved manifest refuses before any Docker query.
        validate_image_lock(lock)
    result = inventory()
    if arguments:
        images(lock)
        result["images"] = "PRESENT_AND_LOCKED_NOT_RUNTIME_TESTED"
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never dump CLI output, config, image labels or an underlying URL.
        code = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        print("VM preflight refused/failed: " + code)
        raise SystemExit(1)
