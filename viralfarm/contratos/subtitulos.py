"""Pista de subtítulos que consume el paso de subtitulado.

Las palabras vienen de dos orígenes y se distinguen visualmente: las del audio original (lo que
dicen en el material) y las de la voz generada.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from viralfarm.contratos.comunes import Base


class OrigenSubtitulo(StrEnum):
    ORIGINAL = "original"
    NARRACION = "narracion"


class Subtitulo(Base):
    """Una palabra en pantalla, en segundos relativos al inicio del episodio."""

    texto: str
    inicio: float = Field(ge=0)
    fin: float = Field(ge=0)
    #: De dónde salió la palabra: define el estilo con que se pinta.
    origen: OrigenSubtitulo

    @model_validator(mode="after")
    def _fin_no_anterior(self) -> Subtitulo:
        if self.fin < self.inicio:
            raise ValueError(f"subtítulo «{self.texto}»: fin ({self.fin}) < inicio ({self.inicio})")
        return self
