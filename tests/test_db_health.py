import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.db.health import CommandResult, format_check_results, run_database_health_checks


class DatabaseHealthTests(unittest.TestCase):
    def test_database_stack_checks_use_docker_compose_and_mark_success(self):
        commands = []

        def runner(command):
            commands.append(list(command))
            joined = " ".join(command)
            if "pg_extension" in joined:
                return CommandResult(stdout="vector\n")
            if "information_schema.tables" in joined:
                return CommandResult(stdout="8\n")
            if command[-2:] == ["redis-cli", "ping"]:
                return CommandResult(stdout="PONG\n")
            raise AssertionError(f"unexpected command: {command}")

        results = run_database_health_checks(runner=runner, compose_file="infra/docker-compose.yml")

        self.assertEqual([result.name for result in results], ["pgvector", "tables", "redis"])
        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(commands[0][:4], ["docker", "compose", "-f", "infra/docker-compose.yml"])
        self.assertIn("vector", results[0].detail)
        self.assertIn("8", results[1].detail)
        self.assertIn("PONG", results[2].detail)

    def test_missing_pgvector_is_reported_as_failure(self):
        def runner(command):
            joined = " ".join(command)
            if "pg_extension" in joined:
                return CommandResult(stdout="")
            if "information_schema.tables" in joined:
                return CommandResult(stdout="8\n")
            return CommandResult(stdout="PONG\n")

        results = run_database_health_checks(runner=runner)

        self.assertFalse(results[0].ok)
        self.assertIn("missing", results[0].detail.lower())
        self.assertTrue(results[1].ok)
        self.assertTrue(results[2].ok)

    def test_format_check_results_shows_failure_and_success(self):
        def runner(command):
            if command[-2:] == ["redis-cli", "ping"]:
                return CommandResult(stdout="NOPE\n")
            if "pg_extension" in " ".join(command):
                return CommandResult(stdout="vector\n")
            return CommandResult(stdout="8\n")

        output = format_check_results(run_database_health_checks(runner=runner))

        self.assertIn("[OK] pgvector", output)
        self.assertIn("[FAIL] redis", output)
        self.assertIn("expected PONG", output)


if __name__ == "__main__":
    unittest.main()
