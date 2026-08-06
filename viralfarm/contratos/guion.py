"""`ep/<n>/guion.json` — capa 4: hook, reparto en tramos, caption y hashtags.

La decisión de diseño clave: el episodio **conserva su duración** y el modelo decide *dónde*
entra la voz. En los tramos `narracion` el audio ambiental se atenúa (ducking) y encima suena
la voz; en los `original` suena el material tal cual. Los tramos cubren el episodio entero, en
orden y sin huecos — el montaje depende de esa invariante.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from viralfarm.contratos.comunes import Base


class TipoTramo(StrEnum):
    ORIGINAL = "original"
    NARRACION = "narracion"


class Tramo(Base):
    """Porción del episodio, en tiempos relativos a su inicio."""

    tipo: TipoTramo
    inicio: float = Field(ge=0)
    fin: float = Field(gt=0)
    #: Texto a narrar; obligatorio en tramos `narracion`, vacío en `original`.
    texto: str = ""

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio

    @model_validator(mode="after")
    def _coherencia(self) -> Tramo:
        if self.fin <= self.inicio:
            raise ValueError(f"tramo {self.inicio}-{self.fin}: fin <= inicio")
        if self.tipo is TipoTramo.NARRACION and not self.texto.strip():
            raise ValueError(f"tramo narracion {self.inicio}-{self.fin} sin texto")
        return self


class Guion(Base):
    indice: int = Field(ge=0)
    #: Idioma de hook, narración y caption (ISO 639-1). Puede no coincidir con el del audio;
    #: el paso de voz elige la voz a partir de él.
    idioma: str = "es"
    #: Frase corta que se superpone al principio del episodio.
    hook: str
    tramos: list[Tramo] = Field(min_length=1)
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)

    # --- formato serie ---
    parte: int | None = Field(default=None, gt=0)
    total_partes: int | None = Field(default=None, gt=0)
    #: Texto del recap narrado que abre el episodio. Ausente en la parte 1.
    recap: str = ""
    #: Resumen de lo que se narró REALMENTE aquí, en el idioma de salida. Es la entrada del
    #: recap del siguiente, y se prefiere al resumen planificado en `serie.json`.
    resumen: str = ""
    #: Tensión abierta al final, tal como quedó narrada.
    cliffhanger: str = ""

    @property
    def duracion(self) -> float:
        return self.tramos[-1].fin if self.tramos else 0.0

    def tramos_narrados(self) -> list[Tramo]:
        return [t for t in self.tramos if t.tipo is TipoTramo.NARRACION]

    def densidad_narracion(self) -> float:
        """Fracción del episodio ocupada por voz en off, en [0, 1].

        El suelo protege la transformatividad; el techo deja respirar al material.
        """
        if self.duracion <= 0:
            return 0.0
        return sum(t.duracion for t in self.tramos_narrados()) / self.duracion

    @model_validator(mode="after")
    def _tramos_encadenados(self) -> Guion:
        """Invariante que necesita el montaje: orden, sin huecos y sin solapes."""
        for anterior, siguiente in zip(self.tramos, self.tramos[1:], strict=False):
            if abs(siguiente.inicio - anterior.fin) > 1e-6:
                raise ValueError(
                    f"guion {self.indice}: hueco o solape entre tramos "
                    f"({anterior.fin} → {siguiente.inicio})"
                )
        return self
