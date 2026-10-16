"""Portable deployment regressions. Standard library only; never call an LLM."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class PlatformScriptsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="autocve platform ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.backend_env = self.root / "backend.env"
        self.compose_env = self.root / "compose.env"
        self.backend_env.write_text("")
        self.compose_env.write_text("")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("VERIFIER_", "DOCKER_", "AUTOCVE_", "LLM_"))}
        self.env.update(PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                        AUTOCVE_ENV_FILE=str(self.backend_env),
                        AUTOCVE_COMPOSE_ENV_FILE=str(self.compose_env))
        self.stub("docker", '''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:3] == ['context', 'inspect']:
    print(os.environ.get('TEST_DOCKER_ENDPOINT', 'unix:///var/run/docker.sock'))
else:
    print(json.dumps({'args': sys.argv[1:], 'env': {k: v for k, v in os.environ.items() if k.startswith('VERIFIER_')}}))
''')

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(source)
        path.chmod(0o755)

    def verify(self, action="config", *args):
        return subprocess.run(["bash", str(REPO / "scripts/verify-stack.sh"), action, *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True)

    def credentials(self, base="https://api.example.test/v1"):
        self.backend_env.write_text(f'LLM_API_KEY="test-only-key"\nLLM_MODEL=test-model\nLLM_BASE_URL={base}\n')

    def test_management_without_model_credentials(self):
        for action in ("ps", "logs", "down", "config", "build"):
            with self.subTest(action=action):
                result = self.verify(action)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(action, json.loads(result.stdout)["args"])

    def test_start_requires_model_configuration(self):
        result = self.verify("up", "-d")
        self.assertEqual(result.returncode, 2)
        self.assertIn("配置不完整", result.stderr)

    def test_default_network_has_no_machine_specific_proxy_or_dns(self):
        self.credentials()
        result = self.verify("up", "-d")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["env"]["VERIFIER_HTTP_PROXY"], "")
        self.assertEqual(payload["env"]["VERIFIER_DNS"], "")
        self.assertFalse(any(arg.endswith("verify.dns.yml") for arg in payload["args"]))

    def test_explicit_empty_proxy_overrides_file(self):
        self.compose_env.write_text("VERIFIER_HTTP_PROXY=http://proxy.example:7897\n")
        self.env["VERIFIER_HTTP_PROXY"] = ""
        payload = json.loads(self.verify().stdout)
        self.assertEqual(payload["env"]["VERIFIER_HTTP_PROXY"], "")
        self.assertEqual(payload["env"]["VERIFIER_HTTPS_PROXY"], "")

    def test_dns_override_is_opt_in(self):
        self.compose_env.write_text("VERIFIER_DNS=10.1.2.53\n")
        payload = json.loads(self.verify().stdout)
        self.assertEqual(payload["env"]["VERIFIER_DNS"], "10.1.2.53")
        self.assertTrue(any(arg.endswith("verify.dns.yml") for arg in payload["args"]))

    def test_empty_compose_proxy_overrides_backend_config(self):
        self.backend_env.write_text("VERIFIER_HTTP_PROXY=http://old-proxy:7897\n")
        self.compose_env.write_text("VERIFIER_HTTP_PROXY=\n")
        payload = json.loads(self.verify().stdout)
        self.assertEqual(payload["env"]["VERIFIER_HTTP_PROXY"], "")

    def test_api_path_is_not_duplicated(self):
        for base, expected in (("https://api.example.test/v1", "https://api.example.test/v1"),
                               ("https://api.example.test/v1/", "https://api.example.test/v1"),
                               ("https://api.example.test/api/v4", "https://api.example.test/api/v4"),
                               ("https://api.example.test", "https://api.example.test/v1")):
            with self.subTest(base=base):
                self.credentials(base)
                payload = json.loads(self.verify().stdout)
                self.assertEqual(payload["env"]["VERIFIER_MODEL_BASE_URL"], expected)

    def test_env_quotes_comments_crlf_and_literal_shell_characters(self):
        sentinel = self.root / "must-not-exist"
        literal = f'test key $(touch "{sentinel}") # literal'
        self.backend_env.write_bytes((f"export LLM_API_KEY='{literal}' # comment\r\n"
                                      'LLM_MODEL="test model" # comment\r\n'
                                      'LLM_BASE_URL=https://api.example.test/v1 # comment\r\n').encode())
        result = self.verify("up", "-d")
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)["env"]
        self.assertEqual(env["VERIFIER_API_KEY"], literal)
        self.assertEqual(env["VERIFIER_MODEL_ID"], "test model")
        self.assertEqual(env["VERIFIER_MODEL_BASE_URL"], "https://api.example.test/v1")
        self.assertFalse(sentinel.exists())

    def helper(self, name):
        result = subprocess.run(["bash", "-c", 'source "$1"; "$2"', "test",
                                 str(REPO / "scripts/lib/platform.sh"), name],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_explicit_docker_host_reaches_sdk(self):
        self.env["DOCKER_HOST"] = "unix:///run/user/1000/docker.sock"
        self.assertEqual(self.helper("autocve_docker_host"), self.env["DOCKER_HOST"])

    def test_context_overrides_docker_host_like_cli(self):
        self.env.update(DOCKER_HOST="unix:///ignored.sock", DOCKER_CONTEXT="selected",
                        TEST_DOCKER_ENDPOINT="unix:///selected.sock")
        self.assertEqual(self.helper("autocve_docker_host"), "unix:///selected.sock")

    def test_linux_rootless_socket_and_macos_vm_socket(self):
        self.env["DOCKER_HOST"] = "unix:///run/user/1000/docker.sock"
        self.stub("uname", "#!/bin/sh\nprintf '%s\\n' Linux\n")
        self.assertEqual(self.helper("autocve_docker_socket"), "/run/user/1000/docker.sock")
        self.stub("uname", "#!/bin/sh\nprintf '%s\\n' Darwin\n")
        self.assertEqual(self.helper("autocve_docker_socket"), "/var/run/docker.sock")

    def test_dind_keeps_upstream_entrypoint_and_optional_flags(self):
        self.stub("dockerd-entrypoint.sh", "#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n")
        script = REPO / "docker/verifier-dind/entrypoint.sh"
        command = ["sh", str(script), "--host=tcp://0.0.0.0:2375", "--tls=false"]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), command[2:])
        self.env.update(VERIFIER_REGISTRY_MIRROR="https://mirror.example", VERIFIER_DNS="10.0.0.53")
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), command[2:] + ["--registry-mirror=https://mirror.example", "--dns=10.0.0.53"])


@unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI not installed")
class ComposeContractTest(unittest.TestCase):
    def config(self, *files, **overrides):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("VERIFIER_", "AUTOCVE_", "COMPOSE_", "WEB_"))}
        env.update(overrides)
        command = ["docker", "compose", "--env-file", os.devnull, "--profile", "discovery"]
        for file in files:
            command.extend(["-f", str(REPO / file)])
        result = subprocess.run(command + ["config", "--format", "json"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_main_services_use_container_socket_and_shared_storage(self):
        services = self.config("docker-compose.yml", AUTOCVE_DOCKER_SOCKET="/run/user/1000/docker.sock")["services"]
        for name in ("backend", "agent-worker", "one-click-cve-worker"):
            with self.subTest(service=name):
                service = services[name]
                self.assertEqual(service["environment"]["DOCKER_HOST"], "unix:///var/run/docker.sock")
                socket = next(v for v in service["volumes"] if v["target"] == "/var/run/docker.sock")
                self.assertEqual(socket["source"], "/run/user/1000/docker.sock")
                self.assertTrue(any(v["target"] == "/app/uploads" for v in service["volumes"]))
        self.assertEqual(services["frontend"]["environment"]["VITE_API_BASE_URL"], "/api/v1")
        self.assertEqual(services["db"]["ports"][0]["host_ip"], "127.0.0.1")

    def test_verifier_default_network_and_shared_work_volume(self):
        services = self.config("docker-compose.verify.yml")["services"]
        for name in ("pi-verifier", "verifier-dind"):
            service = services[name]
            self.assertEqual(service["environment"]["HTTP_PROXY"], "")
            self.assertNotIn("dns", service)
            self.assertFalse(service.get("ports"))
            self.assertTrue(any(v["target"] == "/verifier/work" for v in service["volumes"]))
            self.assertFalse(any(v["target"] == "/var/run/docker.sock" for v in service["volumes"]))

    def test_verifier_explicit_dns_and_proxy(self):
        services = self.config("docker-compose.verify.yml", "docker-compose.verify.dns.yml",
                               VERIFIER_DNS="10.0.0.53", VERIFIER_DNS_FALLBACK="10.0.0.54",
                               VERIFIER_HTTP_PROXY="http://host.docker.internal:7890")["services"]
        for service in services.values():
            self.assertEqual(service["dns"], ["10.0.0.53", "10.0.0.54"])
            self.assertEqual(service["environment"]["HTTP_PROXY"], "http://host.docker.internal:7890")


if __name__ == "__main__":
    unittest.main(verbosity=2)
