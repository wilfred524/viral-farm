"""Fixtures compartidas.

Los *golden files* son los artefactos que produjo el pipeline TypeScript sobre una película
real. Verificar contra ellos es lo que sostiene que la reescritura hace lo mismo y no algo
parecido (ver `docs/arquitectura.md` §9.4).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent
#: Artefactos del pipeline TypeScript. Directorio del formato antiguo (`media/`), a propósito:
#: son los que ya existen, no se regeneran.
GOLDEN = RAIZ / "media" / "pelicula-prueba-05-25-12e8a388"


def _cargar(ruta: Path) -> Any:
    return json.loads(ruta.read_text(encoding="utf-8"))


def hay_golden() -> bool:
    return (GOLDEN / "clips.json").exists() and (GOLDEN / "transcripcion.json").exists()


#: Marca para saltar los tests que necesitan los artefactos reales, sin romper la suite en una
#: máquina limpia donde `media/` no está (no se versiona).
necesita_golden = pytest.mark.skipif(
    not hay_golden(), reason=f"no están los artefactos de referencia en {GOLDEN}"
)


@pytest.fixture(scope="session")
def clips_legado() -> dict[str, Any]:
    return _cargar(GOLDEN / "clips.json")


@pytest.fixture(scope="session")
def transcripcion_legado() -> dict[str, Any]:
    return _cargar(GOLDEN / "transcripcion.json")


@pytest.fixture(scope="session")
def fuente_legado() -> dict[str, Any]:
    return _cargar(GOLDEN / "fuente.json")


@pytest.fixture(scope="session")
def guiones_legado() -> list[dict[str, Any]]:
    """Todos los `clips/<n>/guion.json` que existan, ordenados por índice."""
    rutas = sorted(
        (GOLDEN / "clips").glob("*/guion.json"),
        key=lambda r: int(r.parent.name),
    )
    return [_cargar(r) for r in rutas]


@pytest.fixture(scope="session")
def narraciones_legado() -> list[dict[str, Any]]:
    rutas = sorted(
        (GOLDEN / "clips").glob("*/narracion.json"),
        key=lambda r: int(r.parent.name),
    )
    return [_cargar(r) for r in rutas]
