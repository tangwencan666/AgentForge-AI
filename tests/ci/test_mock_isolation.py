"""Adversarial checks for the hosted boundary, with no services or sockets."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from ci_mock_isolation import audit_guard, hosted_context, inspect_service


class IsolationRefusalTests(unittest.TestCase):
    def test_entrypoint_refuses_before_starting_an_event_loop_or_services(self):
        command = [sys.executable, str(Path(__file__).resolve().parents[2] / 'scripts/ci_mock_workflow.py')]
        environment = {name: os.environ[name] for name in ('PATH', 'SystemRoot', 'WINDIR') if name in os.environ}
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CI_HOSTED_LINUX_REQUIRED', result.stdout)

    def service(self):
        return {'Config': {'Labels': {'ai.agentforge.ci': 'mock-workflow', 'ai.agentforge.ci.run': '123-1',
                                     'ai.agentforge.ci.role': 'postgres'}},
                'HostConfig': {'Privileged': False, 'RestartPolicy': {'Name': 'no'}, 'Binds': None,
                               'Tmpfs': {'/var/lib/postgresql/data': 'rw,nosuid'}},
                'State': {'Running': True, 'Health': {'Status': 'healthy'}}, 'Mounts': [],
                'NetworkSettings': {'Ports': {'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '34567'}]},
                                    'Networks': {'job-network': {'NetworkID': 'a' * 64}}}}

    def test_local_or_self_hosted_execution_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'CI_HOSTED_LINUX_REQUIRED'):
            hosted_context(Path.cwd(), {}, platform='linux')
        with self.assertRaisesRegex(RuntimeError, 'CI_HOSTED_LINUX_REQUIRED'):
            hosted_context(Path.cwd(), {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'self-hosted',
                                        'RUNNER_OS': 'Linux'}, platform='linux')

    def test_attested_ephemeral_service_returns_exact_endpoint(self):
        self.assertEqual(inspect_service(self.service(), 'postgres', '123-1'), (34567, 'a' * 64))

    def test_wrong_run_or_role_is_refused(self):
        for field in ('ai.agentforge.ci.run', 'ai.agentforge.ci.role'):
            row = self.service()
            row['Config']['Labels'][field] = 'other'
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'CI_SERVICE_LABEL_MISMATCH'):
                inspect_service(row, 'postgres', '123-1')

    def test_bind_mount_and_persistent_volume_are_refused(self):
        row = self.service()
        row['HostConfig']['Binds'] = ['/host/data:/var/lib/postgresql/data']
        with self.assertRaisesRegex(RuntimeError, 'CI_PERSISTENT_OR_PRIVILEGED_SERVICE'):
            inspect_service(row, 'postgres', '123-1')
        row = self.service()
        row['Mounts'] = [{'Type': 'volume', 'Destination': '/var/lib/postgresql/data'}]
        with self.assertRaisesRegex(RuntimeError, 'CI_PERSISTENT_MOUNT_FORBIDDEN'):
            inspect_service(row, 'postgres', '123-1')

    def test_public_binding_and_main_port_are_refused(self):
        for update, code in [({'HostIp': '0.0.0.0'}, 'CI_LOOPBACK_REQUIRED'),
                             ({'HostPort': '15432'}, 'CI_RANDOM_PORT_REQUIRED')]:
            row = self.service()
            row['NetworkSettings']['Ports']['5432/tcp'][0].update(update)
            with self.subTest(update=update), self.assertRaisesRegex(RuntimeError, code):
                inspect_service(row, 'postgres', '123-1')

    def test_extra_network_and_privileged_service_are_refused(self):
        row = self.service()
        row['NetworkSettings']['Networks']['other'] = {'NetworkID': 'b' * 64}
        with self.assertRaisesRegex(RuntimeError, 'CI_SERVICE_NETWORK_INVALID'):
            inspect_service(row, 'postgres', '123-1')
        row = self.service()
        row['HostConfig']['Privileged'] = True
        with self.assertRaisesRegex(RuntimeError, 'CI_PERSISTENT_OR_PRIVILEGED_SERVICE'):
            inspect_service(row, 'postgres', '123-1')

    def test_network_guard_denies_models_old_runner_and_other_local_databases(self):
        guard = audit_guard([34567, 34568, 34569])
        guard('socket.connect', (None, ('127.0.0.1', 34567)))
        for address in [('api.deepseek.com', 443), ('127.0.0.1', 18120), ('127.0.0.1', 15432),
                        ('127.0.0.1', 16379), ('/var/run/docker.sock',), ('::1', 34567)]:
            with self.subTest(address=address), self.assertRaisesRegex(RuntimeError, 'CI_NETWORK_ENDPOINT_FORBIDDEN'):
                guard('socket.connect', (None, address))

    def test_dotenv_and_generated_processes_are_refused(self):
        guard = audit_guard([34567], child=True)
        for name in ('.env', '/tmp/.env', '/project/.env.production'):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'CI_DOTENV_READ_FORBIDDEN'):
                guard('open', (name, 'r', 0))
        with self.assertRaisesRegex(RuntimeError, 'CI_CHILD_EXECUTION_FORBIDDEN'):
            guard('subprocess.Popen', ('python', ['python', 'generated.py'], None, {}))


if __name__ == '__main__':
    unittest.main()
