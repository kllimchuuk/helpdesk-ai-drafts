from alembic import command

from tests.helpers import alembic_config, schema_diff, table_names


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
