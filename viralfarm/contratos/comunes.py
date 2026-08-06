"""Tipos compartidos por varios artefactos."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    """Base de todos los contratos.

    `extra="forbid"` es deliberado: un campo inesperado en un artefacto o en una respuesta del
    LLM es una señal de que algo cambió de forma, y se prefiere que falle en el borde.
    """

    model_config = ConfigDict(extra="forbid")


class Palabra(Base):
    """Una palabra con su ventana temporal, en segundos relativos al medio que la contiene."""

    texto: str
    inicio: float = Field(ge=0)
    fin: float = Field(ge=0)


class Segmento(Base):
    inicio: float = Field(ge=0)
    fin: float = Field(ge=0)
    texto: str
    palabras: list[Palabra] = Field(default_factory=list)
