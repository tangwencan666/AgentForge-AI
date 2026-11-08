"""Offline tests: no Engine, service, database, model, dotenv or VM access."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch
from uuid import UUID

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "deploy/vm-mock"
sys.path.insert(0, str(DEMO))
sys.path.insert(0, str(ROOT / "backend"))
import vm_mock_policy as policy


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, DEMO / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = module("vm_demo_runtime", "runtime.py")
preflight = module("vm_demo_preflight", "inspect_target.py")
INSTANCE = "11111111-1111-4111-8111-111111111111"


def environment():
    return {"VM_MOCK_INSTANCE_ID": INSTANCE, "VM_MOCK_APP_PASSWORD": "1" * 64,
            "VM_MOCK_REDIS_PASSWORD": "2" * 64, "VM_MOCK_ADMIN_TOKEN": "3" * 64}


def slots():
    return [{"tenant_id": INSTANCE, "role": role, "provider": "mock", "enabled": True,
             "base_url": None, "credential_reference": None}
            for role in ("planner", "coder", "researcher", "reviewer")]


class PolicyTests(unittest.TestCase):
    def test_foreign_environment_refuses_without_exposing_values(self):
        for name, value in [
            ("AGENTFORGE_SETTINGS_FILE", "never-read/.env"),
            ("AGENTFORGE_DATABASE_URL", "never-connect"),
            ("AGENTFORGE_MODEL_CODER_KEY", "sensitive-sentinel"),
            ("AGENTFORGE_SANDBOX_RUNNER_TOKEN", "sensitive-sentinel"),
            ("AGENTFORGE_REAL_CALLS_ENABLED", "true"),
            ("AGENTFORGE_EXTERNAL_MODELS_BLOCKED", "false"),
            ("OPENAI_API_KEY", "sensitive-sentinel"),
            ("LANGSMITH_API_KEY", "sensitive-sentinel"),
        ]:
            with self.subTest(name=name):
                with self.assertRaises(policy.Refusal) as result:
                    policy.configuration({**environment(), name: value})
                self.assertNotIn(value, str(result.exception))

    def test_distinct_secrets_and_valid_instance_required(self):
        for changes in [
            {"VM_MOCK_ADMIN_TOKEN": "1" * 64},
            {"VM_MOCK_APP_PASSWORD": "short"},
            {"VM_MOCK_INSTANCE_ID": "invalid"},
        ]:
            with self.assertRaises(policy.Refusal):
                policy.configuration({**environment(), **changes})

    def test_slots_cannot_enable_nonmock_or_credential_references(self):
        policy.validate_slots(slots(), INSTANCE)
        for field, value in [("provider", "openai"), ("credential_reference", "env:key"),
                             ("base_url", "https://api.openai.com"), ("enabled", False)]:
            rows = slots()
            rows[0][field] = value
            with self.assertRaises(policy.Refusal):
                policy.validate_slots(rows, INSTANCE)
        with self.assertRaises(policy.Refusal):
            policy.validate_slots(slots()[:3], INSTANCE)

    def test_existing_settings_validators_remain_and_dotenv_is_not_opened(self):
        original_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path.name.startswith(".env"):
                raise AssertionError("dotenv read attempted")
            return original_open(path, *args, **kwargs)
        with patch.dict(os.environ, environment(), clear=True), patch.object(Path, "open", guarded_open):
            from app.core.config import Settings, get_settings
            original_config = dict(Settings.model_config)
            try:
                settings = runtime.settings_from_environment()
                self.assertFalse(settings.real_calls_enabled)
                self.assertFalse(settings.single_use_permits_enabled)
                self.assertEqual(settings.real_worker_mode, "deny")
                self.assertEqual(settings.real_daily_budget_usd, 0)
                self.assertEqual(settings.real_test_budget_usd, 0)
                self.assertGreater(settings.daily_mock_budget_usd, 0)
                self.assertGreater(settings.daily_mock_token_limit, 0)
                self.assertIsNone(settings.sandbox_image_id)
                self.assertIsNone(settings.sandbox_runner_token)
                with self.assertRaises(ValueError):
                    Settings(_env_file=None, database_url="not-valid")
            finally:
                Settings.model_config = original_config
                get_settings.cache_clear()

    def test_local_entrypoint_refuses_before_connections_or_app_import(self):
        result = subprocess.run([sys.executable, str(DEMO / "runtime.py"), "api"],
                                env={"SystemRoot": os.environ.get("SystemRoot", ""),
                                     "PATH": os.environ.get("PATH", "")},
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VM_CONTAINER_REQUIRED", result.stdout)


class Database:
    def __init__(self, tables=0, superuser=False):
        self.tables, self.superuser, self.closed = tables, superuser, False
        self.identity = {"instance": UUID(INSTANCE), "purpose": "agentforge-vm-mock",
                         "base_source": policy.BASE_SOURCE}
        self.model_slots = slots()

    async def fetchval(self, query, *args):
        if "current_database()" in query:
            return "agentforge"
        if "current_user" in query and "rolsuper" not in query:
            return "agentforge_demo"
        if "rolsuper" in query:
            return self.superuser
        if "information_schema" in query:
            return self.tables
        if "alembic_version" in query:
            return "0010_sandbox_maintenance"
        raise AssertionError("unexpected SQL")

    async def fetch(self, query, *args):
        return [self.identity] if "vm_demo_guard" in query else self.model_slots

    async def close(self):
        self.closed = True


class Cache:
    def __init__(self, existing=None, size=0):
        self.existing, self.size, self.writes, self.closed = existing, size, [], False

    async def get(self, key):
        return self.existing

    async def dbsize(self):
        return self.size

    async def set(self, key, value, **options):
        self.writes.append((key, value))
        self.existing = value
        return True

    async def aclose(self):
        self.closed = True


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, database, cache, migration):
        fake_pg = types.ModuleType("asyncpg")
        async def connect(*args, **kwargs):
            return database
        fake_pg.connect = connect
        fake_redis = types.ModuleType("redis.asyncio")
        fake_redis.Redis = types.SimpleNamespace(from_url=lambda *a, **k: cache)
        # Keep Pydantic's lazy module/schema caches outside sys.modules patch
        # restoration. Real Settings validation is covered independently below.
        values = policy.configuration(environment())
        settings = types.SimpleNamespace(
            tenant_id=values["tenant_id"],
            database_url=types.SimpleNamespace(get_secret_value=lambda: values["database_url"]),
            redis_url=types.SimpleNamespace(get_secret_value=lambda: values["redis_url"]))
        with patch.dict(sys.modules, {"asyncpg": fake_pg, "redis": types.ModuleType("redis"),
                                      "redis.asyncio": fake_redis}):
            return await runtime.connect_verified(settings, migration=migration)

    async def test_nonempty_database_refuses_before_redis_write(self):
        db, cache = Database(tables=1), Cache()
        with self.assertRaisesRegex(policy.Refusal, "EMPTY_DATABASE"):
            await self.connect(db, cache, True)
        self.assertEqual(cache.writes, [])
        self.assertTrue(db.closed and cache.closed)

    async def test_wrong_identity_or_superuser_refuses_before_redis_write(self):
        for db in (Database(superuser=True), Database()):
            if not db.superuser:
                db.identity["instance"] = UUID("22222222-2222-4222-8222-222222222222")
            cache = Cache()
            with self.assertRaises(policy.Refusal):
                await self.connect(db, cache, True)
            self.assertEqual(cache.writes, [])

    async def test_foreign_redis_data_refuses_without_write(self):
        cache = Cache(size=2)
        with self.assertRaisesRegex(policy.Refusal, "FRESH_REDIS"):
            await self.connect(Database(), cache, True)
        self.assertEqual(cache.writes, [])

    async def test_api_worker_never_create_a_missing_marker(self):
        cache = Cache()
        with self.assertRaisesRegex(policy.Refusal, "REDIS_IDENTITY"):
            await self.connect(Database(), cache, False)
        self.assertEqual(cache.writes, [])

    async def test_only_empty_marked_migration_target_can_initialize_redis(self):
        db, cache = Database(), Cache()
        await self.connect(db, cache, True)
        self.assertEqual(len(cache.writes), 1)
        self.assertEqual(json.loads(cache.existing)["instance"], INSTANCE)

    async def test_matching_runtime_target_is_read_only(self):
        marker = json.dumps({"instance": INSTANCE, "base_source": policy.BASE_SOURCE}, sort_keys=True)
        db, cache = Database(tables=10), Cache(existing=marker, size=4)
        await self.connect(db, cache, False)
        self.assertEqual(cache.writes, [])
        db.model_slots[0]["provider"] = "real-provider"
        with self.assertRaisesRegex(policy.Refusal, "NON_MOCK"):
            await self.connect(db, cache, False)


class TargetTests(unittest.TestCase):
    def fake(self, engine=preflight.EXPECTED_ENGINE, running=False, extra_volume=False):
        calls = []
        def call(*arguments):
            calls.append(arguments)
            if arguments[:2] == ("info", "--format"):
                return engine if arguments[-1] == "{{.ID}}" else "inactive"
            if arguments == ("ps", "-aq"):
                return "\n".join(sorted(preflight.KNOWN_CONTAINERS))
            if arguments[0] == "inspect":
                return json.dumps({"name": "/" + arguments[3], "running": running,
                                   "status": "running" if running else "exited", "restart": "no"})
            if arguments[0] == "network":
                return "bridge\nhost\nnone"
            if arguments[0] == "volume":
                return "mysql-data\nredis-data" + ("\nagentforge-vm-mock-postgres-data" if extra_volume else "")
            raise AssertionError("mutation or unexpected Docker command")
        return call, calls

    def test_wrong_engine_refuses_before_container_inventory(self):
        call, calls = self.fake(engine="windows-or-other-engine")
        with self.assertRaisesRegex(RuntimeError, "WRONG_ENGINE"):
            preflight.inventory(call)
        self.assertEqual(len(calls), 1)

    def test_running_workload_or_name_collision_refuses(self):
        for changes in ({"running": True}, {"extra_volume": True}):
            with self.subTest(changes=changes):
                with self.assertRaises(RuntimeError):
                    preflight.inventory(self.fake(**changes)[0])

    def test_inventory_uses_actual_states_without_summary_running_count(self):
        call, calls = self.fake()
        result = preflight.inventory(call)
        self.assertEqual(len(result["containers"]), 5)
        self.assertTrue(all(c[0] in {"info", "ps", "inspect", "network", "volume"} for c in calls))
        self.assertFalse(any("ContainersRunning" in str(c) for c in calls))

    def test_unbuilt_manifest_is_not_accepted_as_prebuilt(self):
        lock = json.loads((DEMO / "images.lock.json").read_text())
        with self.assertRaisesRegex(RuntimeError, "NOT_BUILT"):
            preflight.validate_image_lock(lock)

    def test_windows_host_refuses_before_docker_query(self):
        with patch.object(sys, "platform", "win32"), patch("subprocess.check_output") as command:
            with self.assertRaisesRegex(RuntimeError, "LINUX_HOST"):
                preflight.main()
            command.assert_not_called()

    def test_immutable_refs_and_tagless_repo_digests(self):
        lock = json.loads((DEMO / "images.lock.json").read_text())
        lock["build_status"] = "BUILT"
        for name in ("backend", "frontend"):
            lock["artifacts"][name].update(
                reference="ghcr.io/fixture/" + name + "@sha256:" + "a" * 64,
                build_revision="b" * 40)
        def inspect(*args):
            reference = args[2]
            repo, digest = reference.split("@")
            return json.dumps({"id": "sha256:" + "c" * 64, "digests": [repo.split(":")[0] + "@" + digest],
                               "architecture": "amd64", "os": "linux",
                               "labels": {"ai.agentforge.demo": "vm-mock",
                                          "org.opencontainers.image.revision": "b" * 40,
                                          "org.opencontainers.image.source": "https://github.com/tangwencan666/AgentForge-AI"}})
        preflight.images(lock, inspect)
        lock["artifacts"]["backend"]["reference"] = "fixture:latest"
        with self.assertRaisesRegex(RuntimeError, "IMMUTABLE"):
            preflight.validate_image_lock(lock)

    def test_offline_image_ids_match_config_and_do_not_require_registry_digest(self):
        lock = json.loads((DEMO / "images.lock.json").read_text())
        lock["build_status"] = "BUILT"
        identity = "sha256:" + "a" * 64
        for name in ("backend", "frontend"):
            lock["artifacts"][name].update(reference=identity, config_digest=identity,
                                           image_id=identity, build_revision="b" * 40)
        lock['official_dependencies'] = {name: {'image_id': identity} for name in ('postgres', 'redis')}
        def inspect(*args):
            return json.dumps({"id": identity, "digests": [], "architecture": "amd64", "os": "linux",
                "labels": {"ai.agentforge.demo": "vm-mock", "org.opencontainers.image.revision": "b" * 40,
                           "org.opencontainers.image.source": "https://github.com/tangwencan666/AgentForge-AI"}})
        preflight.images(lock, inspect)
        lock['artifacts']['backend']['config_digest'] = 'sha256:' + 'c' * 64
        with self.assertRaisesRegex(RuntimeError, 'CONFIG_LOCK'):
            preflight.validate_image_lock(lock)


class HostedTests(unittest.TestCase):
    def test_host_attestation_refuses_vm_and_windows_engine_before_other_calls(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import ci_vm_common
        for identity in ci_vm_common.FORBIDDEN_ENGINES:
            with patch.object(ci_vm_common, 'hosted_context', return_value='1-1'), \
                 patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'pull_request'}), \
                 patch.object(ci_vm_common, 'docker', return_value=json.dumps({'ID': identity})) as call:
                with self.assertRaisesRegex(RuntimeError, 'ENGINE_MISMATCH'):
                    ci_vm_common.attest()
                self.assertEqual(call.call_count, 1)

    def test_new_entrypoints_refuse_local_before_docker(self):
        for name in ('ci_vm_images.py', 'ci_vm_compose.py'):
            with self.subTest(name=name):
                result = subprocess.run([sys.executable, str(ROOT / 'scripts' / name)],
                    env={'SystemRoot': os.environ.get('SystemRoot', ''), 'PATH': os.environ.get('PATH', '')},
                    capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('CI_HOSTED_LINUX_REQUIRED', result.stdout)

    def test_oci_identity_verifies_manifest_and_config_bytes(self):
        import io
        import tarfile
        import tempfile
        sys.path.insert(0, str(ROOT / 'scripts'))
        from ci_vm_images import oci_identity
        config = b'{"architecture":"amd64","os":"linux"}'
        config_digest = hashlib.sha256(config).hexdigest()
        manifest = json.dumps({'config': {'digest': 'sha256:' + config_digest}}).encode()
        manifest_digest = hashlib.sha256(manifest).hexdigest()
        index = json.dumps({'manifests': [{'digest': 'sha256:' + manifest_digest}]}).encode()
        for damaged in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'image.tar'
                with tarfile.open(target, 'w') as archive:
                    for name, content in [('index.json', index), ('blobs/sha256/' + manifest_digest, manifest),
                                          ('blobs/sha256/' + config_digest, b'bad' if damaged else config)]:
                        entry = tarfile.TarInfo(name)
                        entry.size = len(content)
                        archive.addfile(entry, io.BytesIO(content))
                if damaged:
                    with self.assertRaisesRegex(RuntimeError, 'CONFIG_DIGEST'):
                        oci_identity(target)
                else:
                    self.assertEqual(oci_identity(target), ('sha256:' + manifest_digest, 'sha256:' + config_digest))


class ComposeTests(unittest.TestCase):
    def test_no_published_ports_host_network_external_data_or_runner(self):
        config = yaml.safe_load((DEMO / "compose.yaml").read_text())
        self.assertEqual(set(config["services"]), {"postgres", "redis", "migrate", "backend", "worker", "frontend"})
        for service in config["services"].values():
            self.assertFalse(set(service) & {"ports", "network_mode", "privileged", "devices", "build"})
            self.assertTrue(service["read_only"])
            self.assertEqual(service["pull_policy"], "never")
            self.assertEqual(service["restart"], "no")
        self.assertTrue(all(n["internal"] for n in config["networks"].values()))
        for values in (config["networks"], config["volumes"]):
            self.assertTrue(all(x["name"].startswith(preflight.PREFIX) and not x.get("external") for x in values.values()))
        self.assertNotIn("migration", config["services"]["backend"]["profiles"])
        self.assertEqual(config["services"]["migrate"]["profiles"], ["migration"])
        self.assertNotIn("data", config["services"]["backend"]["profiles"])

    def test_credential_free_context_and_dependency_locks(self):
        ignore = (ROOT / ".dockerignore").read_text()
        self.assertIn("**/.env", ignore)
        self.assertIn("**/.env.*", ignore)
        self.assertEqual(ignore.splitlines()[1], "*")
        lock = json.loads((DEMO / "images.lock.json").read_text())
        for filename, digest in lock["dependency_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), digest)
        self.assertEqual(lock["base_source_revision"], policy.BASE_SOURCE)


if __name__ == "__main__":
    unittest.main()
