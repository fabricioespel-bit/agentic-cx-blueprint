"""Fixtures compartilhadas dos testes unitários."""

from datetime import UTC, datetime, timedelta

import pytest


class RelogioFixo:
    """Relógio controlado pelo teste."""

    def __init__(self) -> None:
        self.agora = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.agora

    def avancar(self, **delta: float) -> None:
        self.agora += timedelta(**delta)


@pytest.fixture
def relogio() -> RelogioFixo:
    return RelogioFixo()
