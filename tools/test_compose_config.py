import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("docker"), "Docker Compose is required")
class ComposeConfigurationTests(unittest.TestCase):
    def render(self, prefix):
        values = {
            "MONGO_ROOT_USER": "test-user", "MONGO_ROOT_PASSWORD": "test-password",
            "JWT_SECRET_KEY": "test-signing-key", "PLATFORM_ADMIN_EMAIL": "admin@example.test",
            "PLATFORM_ADMIN_PASSWORD": "test-admin-password", "LLM_ANALYSIS_ENABLED": "true",
            "KAFKA_BOOTSTRAP_SERVERS": "test-kafka:9092", "APP_RELEASE_VERSION": "0.2.0",
            "APP_RELEASE_SHA": "a" * 40, "OLLAMA_MODEL": "test-model",
            "OLLAMA_URL": "http://configured-ollama:11434",
        }
        env = {key: value for key, value in os.environ.items()
               if key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT")}
        env.update({prefix + key: value for key, value in values.items()})
        env["TIERX_SOURCE_REPOSITORY"] = "https://github.com/example/tierx"
        env["NEXT_PUBLIC_TIERX_API_URL"] = ""
        output = subprocess.check_output(
            ["docker", "compose", "--env-file", "/dev/null", "-f", "compose.yaml", "config", "--format", "json"],
            cwd=ROOT, env=env, text=True,
        )
        return json.loads(output)["services"]

    def test_supported_environment_families_reach_containers(self):
        for prefix in ("TIERX_", "", "SOC_MIND_"):
            with self.subTest(prefix=prefix):
                services = self.render(prefix)
                self.assertEqual(services["mongodb"]["environment"]["MONGO_INITDB_ROOT_USERNAME"], "test-user")
                self.assertEqual(services["backend"]["environment"]["JWT_SECRET_KEY"], "test-signing-key")
                self.assertEqual(services["pipeline"]["environment"]["LLM_ANALYSIS_ENABLED"], "true")
                self.assertEqual(services["init"]["environment"]["OLLAMA_MODEL"], "test-model")
                self.assertEqual(services["kb-semantic"]["environment"]["OLLAMA_URL"], "http://configured-ollama:11434")
                for service in ("qdrant", "kb-semantic"):
                    self.assertEqual(services[service]["logging"]["options"], {"max-size": "10m", "max-file": "3"})
                self.assertEqual(services["ingestion-proxy"]["environment"]["KAFKA_BOOTSTRAP_SERVERS"], "test-kafka:9092")

    def test_frontend_release_values_are_build_arguments(self):
        args = self.render("TIERX_")["frontend"]["build"]["args"]
        self.assertEqual(args["NEXT_PUBLIC_TIERX_API_URL"], "")
        self.assertEqual(args["NEXT_PUBLIC_TIERX_RELEASE_VERSION"], "0.2.0")
        self.assertEqual(args["NEXT_PUBLIC_TIERX_RELEASE_SHA"], "a" * 40)
        self.assertEqual(args["NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY"], "https://github.com/example/tierx")
