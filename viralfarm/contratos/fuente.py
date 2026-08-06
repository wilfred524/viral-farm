"""`fuente.json` — descripción del video de entrada."""

from __future__ import annotations

from pydantic import Field

from viralfarm.contratos.comunes import Base


class Fuente(Base):
    video_id: str
    ruta_original: str
    duracion: float = Field(gt=0)
    ancho: int = Field(gt=0)
    alto: int = Field(gt=0)
    fps: float = Field(gt=0)
    #: Rotación declarada en metadata (los MOV de móvil suelen traer 90).
    rotacion: float = 0.0
    codec_video: str
    codec_audio: str | None = None
    creado_en: str
