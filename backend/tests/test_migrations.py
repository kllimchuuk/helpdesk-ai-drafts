import os
import subprocess
import sys

from alembic import command

from tests.helpers import BACKEND_DIR, alembic_config, schema_diff, table_names


def test_upgrade_creates_the_ticket_events_table(throwaway_database: str) -> None:
    command.upgrade(alembic_config(throwaway_database), "head")

    assert "ticket_events" in table_names(throwaway_database)


def test_models_and_migrations_describe_the_same_schema(
    throwaway_database: str,
) -> None:
    command.upgrade(alembic_config(throwaway_database), "head")

    assert schema_diff(throwaway_database) == []


def test_downgrade_removes_what_upgrade_created(throwaway_database: str) -> None:
    config = alembic_config(throwaway_database)
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    assert table_names(throwaway_database) == ["alembic_version"]


def test_containers_migrating_at_the_same_time_do_not_fail(
    throwaway_database: str,
) -> None:
    environment = {
        **os.environ,
        "DATABASE_URL": throwaway_database,
        "PYTHONPATH": str(BACKEND_DIR / "src"),
    }
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]

    outcomes = [
        (process.communicate(timeout=60), process.returncode) for process in processes
    ]

    assert [code for _, code in outcomes] == [0, 0, 0, 0], outcomes
    assert "ticket_events" in table_names(throwaway_database)
