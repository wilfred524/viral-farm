"""`timeline.json` — línea de tiempo multimodal.

Fusiona diálogo, acciones vistas y silencios en UNA secuencia ordenada. Es el nuevo contrato de
entrada del paso de selección: gracias a él se puede añadir percepción y visión sin tocar nada
aguas abajo (ver `docs/arquitectura.md` §6.2).

Hoy se construye solo con diálogo y silencios —el equivalente de lo que el TypeScript metía
directamente en el prompt— y admite acciones en cuanto exista `vision.json`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from viralfarm.contratos.comunes import Base


class TipoEvento(StrEnum):
    DIALOGO = "dialogo"
    ACCION = "accion"
    SILENCIO = "silencio"


class EventoTimeline(Base):
    tipo: TipoEvento
    inicio: float = Field(ge=0)
    fin: float = Field(gt=0)
    texto: str
    #: Solo en eventos de audio/visión: intensidad normalizada a [0, 1].
    intensidad: float | None = Field(default=None, ge=0, le=1)

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio


class Timeline(Base):
    duracion: float = Field(gt=0)
    #: Idioma del diálogo transcrito.
    idioma: str
    #: True si la línea de tiempo incorpora observaciones visuales.
    con_vision: bool = False
    eventos: list[EventoTimeline] = Field(default_factory=list)
