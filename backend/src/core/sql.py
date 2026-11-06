from enum import StrEnum

from sqlalchemy import CheckConstraint


def enum_check(column: str, name: str, enum: type[StrEnum]) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=name)
