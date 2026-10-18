"""Identity: who you are. The role always comes from the server-side users table."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from starlette.requests import Request


@dataclass(frozen=True)
class Principal:
    username: str
    name: str
    title: str
    department: str
    role: str

    @property
    def initials(self) -> str:
        return "".join(part[0] for part in self.name.split()[:2]).upper()

    def to_dict(self) -> dict:
        return asdict(self)


class IdentityProvider(Protocol):
    def current_principal(self, request: Request) -> Principal | None:
        """Return the signed-in person, None if nobody is signed in.
        Raise core.errors.InvalidToken for a credential that is present but not valid."""
        ...


def principal_from_row(row) -> Principal:
    return Principal(
        username=row["username"],
        name=row["name"],
        title=row["title"],
        department=row["department"],
        role=row["role"],
    )
