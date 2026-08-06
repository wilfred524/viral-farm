"""`ep/<n>/voz.json` — narración sintetizada, con timings por palabra.

Sustituye al `narracion.json` del pipeline TypeScript. Los timings por palabra son lo que
permite sincronizar los subtítulos karaoke de la voz generada.
"""

from __future__ import annotations

from pydantic import Field

from viralfarm.contratos.comunes import Base, Palabra


class VozTramo(Base):
    """Audio sintetizado para un tramo `narracion` del guion."""

    #: Índice del tramo dentro de `guion.tramos`.
    tramo: int = Field(ge=0)
    archivo: str
    #: Segundo del episodio en el que arranca el audio narrado.
    desplazamiento: float = Field(ge=0)
    #: Duración ya ajustada por `tempo`.
    duracion: float = Field(gt=0)
    #: Factor `atempo` aplicado para encajar el audio en el tramo (1 = sin ajuste).
    tempo: float = Field(default=1.0, gt=0)
    #: Timings relativos al mp3; con tempo != 1 se comprimen igual que el audio.
    palabras: list[Palabra] = Field(default_factory=list)

    @property
    def fin(self) -> float:
        return self.desplazamiento + self.duracion


class Voz(Base):
    voz: str
    tramos: list[VozTramo] = Field(default_factory=list)

    def por_tramo(self, indice: int) -> VozTramo | None:
        return next((t for t in self.tramos if t.tramo == indice), None)
