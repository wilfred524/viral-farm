"""Paso de selección: de la película a la serie de episodios.

El modelo propone; `dominio/episodios.py` verifica y repara. Este módulo solo aporta el texto
y el contrato de la respuesta.

Los campos de la respuesta usan camelCase porque ese es el formato que el modelo genera con
más naturalidad y el que consume el pipeline TypeScript mientras dure la migración. El
artefacto que se escribe a disco es otra cosa (`contratos/serie.py`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from viralfarm.dominio.episodios import (
    COBERTURA_MAX,
    COLA_MINIMA,
    DURACION_MAX,
    DURACION_MIN,
    DURACION_OBJETIVO,
)
from viralfarm.prompts import plantillas


#: El texto vive en `plantillas/serie.sistema.md`. Se lee al usarlo, no al importar, para
#: que editar el markdown no obligue a reiniciar nada.
def sistema() -> str:
    """Instrucciones de cómo dividir la película en episodios."""
    return plantillas.render("serie.sistema")


def version_sistema() -> str:
    return plantillas.version("serie.sistema")


class EpisodioPropuestoLlm(BaseModel):
    """Un episodio tal como lo propone el modelo, en segundos absolutos del fuente."""

    model_config = ConfigDict(populate_by_name=True)

    inicio: float = Field(description="Segundo absoluto de inicio en el video fuente")
    fin: float = Field(description="Segundo absoluto de fin en el video fuente")
    titulo: str = Field(description="Título del episodio, con gancho, SIN el número de parte")
    razon: str = Field(description="Por qué este tramo funciona como episodio autónomo")
    cumbre: float = Field(description="Segundo ABSOLUTO del pico de tensión")
    desenlace: float = Field(description="Segundo ABSOLUTO en que se cierra el arco abierto")
    resumen: str = Field(description="2-3 frases de lo que ocurre; base del recap siguiente")
    cliffhanger: str = Field(description="La tensión que queda abierta al final, en una frase")
    puntuacion: float = Field(description="0-10, cuánto engancha el episodio")


class RespuestaSerie(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    titulo_serie: str = Field(alias="tituloSerie", description="Título de la serie completa")
    sinopsis: str = Field(description="Sinopsis de la serie en 2-3 frases")
    episodios: list[EpisodioPropuestoLlm]


def construir_prompt(
    transcripcion_formateada: str,
    duracion_fuente: float,
    max_episodios: int,
    idioma_origen: str,
    idioma_salida: str,
) -> str:
    """Prompt de usuario. `transcripcion_formateada` viene de `dominio.timeline`.

    Los límites numéricos se interpolan desde el dominio, no se escriben en el markdown: así
    el prompt no puede prometerle al modelo un tope distinto del que el código le va a
    exigir después, que es como se llega a que el guion se recorte solo.
    """
    return plantillas.render(
        "serie.usuario",
        duracion=f"{duracion_fuente:.0f}",
        minutos=f"{duracion_fuente / 60:.0f}",
        idioma_origen=idioma_origen,
        timeline=transcripcion_formateada,
        max_episodios=max_episodios,
        idioma_salida=idioma_salida,
        duracion_min=f"{DURACION_MIN:.0f}",
        duracion_max=f"{DURACION_MAX:.0f}",
        duracion_objetivo=f"{DURACION_OBJETIVO:.0f}",
        cobertura_max=f"{COBERTURA_MAX * 100:.0f}",
        cola_minima=f"{COLA_MINIMA:.0f}",
    )


def version_usuario() -> str:
    return plantillas.version("serie.usuario")
