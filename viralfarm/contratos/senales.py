"""`senales.json` — capa 1 (percepción): trazas objetivas de audio y video, sin IA.

Determinista, barato y reproducible. Dice **dónde pasa algo** sin gastar un token, y es lo que
dirige el muestreo de frames de la capa de visión (ver `docs/arquitectura.md` §6.1).
"""

from __future__ import annotations

from pydantic import Field

from viralfarm.contratos.comunes import Base


class VentanaAudio(Base):
    """Medición de una ventana temporal del audio."""

    inicio: float = Field(ge=0)
    fin: float = Field(gt=0)
    #: Energía RMS normalizada a [0, 1] sobre el máximo del material.
    energia: float = Field(ge=0, le=1)
    #: Sonoridad integrada de la ventana, en LUFS. Negativa por definición.
    lufs: float | None = None
    #: Proporción de la ventana con habla detectada, en [0, 1].
    habla: float = Field(default=0.0, ge=0, le=1)
    #: True si la ventana está por debajo del umbral de silencio.
    silencio: bool = False


class CorteVisual(Base):
    """Cambio de plano detectado, en segundos absolutos del fuente."""

    tiempo: float = Field(ge=0)
    #: Puntuación del filtro `scene` de ffmpeg que lo disparó.
    intensidad: float = Field(ge=0, le=1)


class Senales(Base):
    duracion: float = Field(gt=0)
    #: Tamaño de la ventana de análisis de audio, en segundos.
    ventana_seg: float = Field(gt=0)
    audio: list[VentanaAudio] = Field(default_factory=list)
    cortes: list[CorteVisual] = Field(default_factory=list)
    #: Instantes candidatos a ser muestreados por la capa de visión, ya priorizados.
    instantes_interes: list[float] = Field(default_factory=list)
