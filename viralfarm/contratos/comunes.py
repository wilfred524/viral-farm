"""Tipos compartidos por varios artefactos."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    """Base de todos los contratos.

    `extra="forbid"` es deliberado: un campo inesperado en un artefacto o en una respuesta del
    LLM es una señal de que algo cambió de forma, y se prefiere que falle en el borde.
    """

    model_config = ConfigDict(extra="forbid")


class Procedencia(Base):
    """Qué produjo un artefacto generado por un modelo.

    Existe por una razón concreta: refinar prompts es un proceso iterativo, y sin saber qué
    versión de texto generó cada salida no se puede atribuir una mejora a un cambio. Las
    versiones son el hash del contenido de la plantilla (`prompts.plantillas.version`), así
    que dos guiones con la misma pareja de hashes son comparables entre sí.
    """

    modelo: str = ""
    prompt_sistema: str = ""
    prompt_usuario: str = ""

    @property
    def etiqueta(self) -> str:
        """Identificador corto de la combinación, para nombrar carpetas y filas de tabla."""
        return f"{self.prompt_sistema or '?'}+{self.prompt_usuario or '?'}"


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
