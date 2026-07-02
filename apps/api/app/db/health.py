from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable, List, Sequence


DEFAULT_COMPOSE_FILE = "infra/docker-compose.yml"
DEFAULT_EXPECTED_TABLES = 8


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str = ""
    returncode: int = 0


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    ok: bool
    detail: str


CommandRunner = Callable[[Sequence[str]], CommandResult]


def default_runner(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(
        list(command),
        capture_output=True,
        check=False,
        text=True,
    )
    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def compose_exec_command(
    service: str,
    command: Iterable[str],
    *,
    compose_file: str = DEFAULT_COMPOSE_FILE,
) -> List[str]:
    return ["docker", "compose", "-f", compose_file, "exec", "-T", service, *command]


def run_database_health_checks(
    *,
    runner: CommandRunner = default_runner,
    compose_file: str = DEFAULT_COMPOSE_FILE,
    postgres_user: str = "radar",
    postgres_database: str = "radar",
    expected_tables: int = DEFAULT_EXPECTED_TABLES,
) -> List[HealthCheckResult]:
    return [
        _check_pgvector(runner, compose_file, postgres_user, postgres_database),
        _check_tables(runner, compose_file, postgres_user, postgres_database, expected_tables),
        _check_redis(runner, compose_file),
    ]


def format_check_results(results: Sequence[HealthCheckResult]) -> str:
    lines = []
    for result in results:
        status = "OK" if result.ok else "FAIL"
        lines.append(f"[{status}] {result.name}: {result.detail}")
    return "\n".join(lines)


def all_checks_passed(results: Sequence[HealthCheckResult]) -> bool:
    return all(result.ok for result in results)


def _check_pgvector(
    runner: CommandRunner,
    compose_file: str,
    postgres_user: str,
    postgres_database: str,
) -> HealthCheckResult:
    sql = "SELECT extname FROM pg_extension WHERE extname='vector';"
    command = compose_exec_command(
        "postgres",
        ["psql", "-U", postgres_user, "-d", postgres_database, "-tAc", sql],
        compose_file=compose_file,
    )
    return _run_check(
        "pgvector",
        command,
        runner,
        lambda stdout: _expect_exact(stdout, "vector", "vector extension available"),
    )


def _check_tables(
    runner: CommandRunner,
    compose_file: str,
    postgres_user: str,
    postgres_database: str,
    expected_tables: int,
) -> HealthCheckResult:
    sql = "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
    command = compose_exec_command(
        "postgres",
        ["psql", "-U", postgres_user, "-d", postgres_database, "-tAc", sql],
        compose_file=compose_file,
    )
    return _run_check(
        "tables",
        command,
        runner,
        lambda stdout: _expect_table_count(stdout, expected_tables),
    )


def _check_redis(runner: CommandRunner, compose_file: str) -> HealthCheckResult:
    command = compose_exec_command(
        "redis",
        ["redis-cli", "ping"],
        compose_file=compose_file,
    )
    return _run_check(
        "redis",
        command,
        runner,
        lambda stdout: _expect_exact(stdout, "PONG", "PONG received"),
    )


def _run_check(
    name: str,
    command: Sequence[str],
    runner: CommandRunner,
    validator: Callable[[str], tuple[bool, str]],
) -> HealthCheckResult:
    try:
        result = runner(command)
    except OSError as exc:
        return HealthCheckResult(name=name, ok=False, detail=str(exc))

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        return HealthCheckResult(name=name, ok=False, detail=detail)

    ok, detail = validator(result.stdout.strip())
    return HealthCheckResult(name=name, ok=ok, detail=detail)


def _expect_exact(stdout: str, expected: str, success_detail: str) -> tuple[bool, str]:
    if stdout == expected:
        return True, success_detail
    actual = stdout or "<empty>"
    return False, f"missing expected {expected} (got {actual})"


def _expect_table_count(stdout: str, expected_tables: int) -> tuple[bool, str]:
    try:
        table_count = int(stdout)
    except ValueError:
        actual = stdout or "<empty>"
        return False, f"expected table count >= {expected_tables} (got {actual})"

    if table_count >= expected_tables:
        return True, f"{table_count} public tables available"
    return False, f"expected table count >= {expected_tables} (got {table_count})"
