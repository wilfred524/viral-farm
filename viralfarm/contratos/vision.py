"""`vision.json` — capa 2 (comprensión): qué ocurre en pantalla.

Los frames NO se muestrean a intervalo fijo: se eligen donde `senales.json` indica evento. Un
frame cada 10 s de una película de 90 min son 540 imágenes; dirigidos por señales son ~60 bien
elegidas (ver `docs/arquitectura.md` §6.1).
"""

from __future__ import annotations

from pydantic import Field

from viralfarm.contratos.comunes import Base


class Observacion(Base):
    """Lo que el modelo de visión ve en un instante concreto del fuente."""

    tiempo: float = Field(ge=0)
    #: Qué ocurre en pantalla, en una o dos frases.
    accion: str
    #: Quién aparece, si es identificable dentro del propio material.
    personajes: list[str] = Field(default_factory=list)
    #: Dónde ocurre.
    escenario: str = ""
    #: Carga dramática percibida, 0-10. El código la contrasta con la energía de audio.
    intensidad: float = Field(default=0.0, ge=0, le=10)


class Vision(Base):
    modelo: str
    #: Cuántos frames se enviaron al modelo. Sirve para auditar el coste de la capa.
    frames_analizados: int = Field(ge=0)
    observaciones: list[Observacion] = Field(default_factory=list)
