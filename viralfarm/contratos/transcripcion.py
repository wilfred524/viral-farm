"""`transcripcion.json` — salida de faster-whisper con timestamps por palabra."""

from __future__ import annotations

from pydantic import Field

from viralfarm.contratos.comunes import Base, Segmento


class Transcripcion(Base):
    #: ISO 639-1 detectado por Whisper, o el forzado por configuración.
    idioma: str
    modelo: str
    duracion: float = Field(ge=0)
    segmentos: list[Segmento] = Field(default_factory=list)

    def total_palabras(self) -> int:
        return sum(len(s.palabras) for s in self.segmentos)
