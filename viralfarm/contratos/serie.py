"""`candidatos.json` y `serie.json` — capa 3 (decisión).

Se persiste por separado **lo que el sistema consideró** (`candidatos.json`) y **lo que eligió
producir** (`serie.json`). Esa separación es la que hace auditable la decisión: sin ella no hay
forma de saber qué se descartó ni por qué (ver `docs/arquitectura.md` §6.1).

Nomenclatura: lo que el pipeline TypeScript llamaba *clip* aquí es un **episodio**, porque el
producto por defecto es una serie. El formato legado de fragmentos sueltos conserva el nombre
`virales`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from viralfarm.contratos.comunes import Base, Procedencia


class Formato(StrEnum):
    SERIE = "serie"
    VIRALES = "virales"


class Alineacion(StrEnum):
    """De qué dependió una frontera: diagnóstico de la calidad del corte."""

    ESCENA = "escena"
    FRASE = "frase"
    LLM = "llm"


class Arco(Base):
    """Anatomía del arco narrativo, en segundos relativos al inicio del episodio.

    Entre `desenlace` y el final va el cierre en tensión: lo que engancha con la entrega
    siguiente.
    """

    #: Pico de tensión.
    cumbre: float = Field(ge=0)
    #: Instante en que se cierra el arco que abrió el episodio.
    desenlace: float = Field(ge=0)


class AlineacionFronteras(Base):
    inicio: Alineacion = Alineacion.LLM
    fin: Alineacion = Alineacion.LLM


#: Peso de cada componente del score. Explícito y fuera del contrato para poder recalibrarlo
#: cuando haya resultados reales, sin invalidar artefactos ya escritos.
PESOS_SCORE: dict[str, float] = {
    "densidad_eventos": 0.25,
    "fuerza_cierre": 0.30,
    "autonomia": 0.20,
    "calidad_cortes": 0.10,
    "juicio_llm": 0.15,
}


class ScoreEpisodio(Base):
    """Score **desglosado**, nunca un número opaco.

    Cada componente va en [0, 1] y se persiste por separado para poder inspeccionarlo y, más
    adelante, recalibrarlo contra resultados reales.
    """

    #: Densidad de eventos relevantes según `senales.json` / `timeline.json`.
    densidad_eventos: float = Field(default=0.0, ge=0, le=1)
    #: Cuánta tensión queda abierta al final. El motor de la serie.
    fuerza_cierre: float = Field(default=0.0, ge=0, le=1)
    #: Si se entiende sin haber visto lo anterior.
    autonomia: float = Field(default=0.0, ge=0, le=1)
    #: Cortes en cambio de plano > en frontera de frase > donde dijo el modelo.
    calidad_cortes: float = Field(default=0.0, ge=0, le=1)
    #: Juicio cualitativo del modelo, 0-1. Es UNA señal más, no el score.
    juicio_llm: float = Field(default=0.0, ge=0, le=1)

    @property
    def total(self) -> float:
        """Media ponderada de los componentes, en [0, 1].

        Los pesos son `PESOS_SCORE`: viven fuera del artefacto porque son política, no dato.
        Recalibrarlos no debe cambiar el esquema de nada ya escrito en disco.
        """
        return (
            self.densidad_eventos * PESOS_SCORE["densidad_eventos"]
            + self.fuerza_cierre * PESOS_SCORE["fuerza_cierre"]
            + self.autonomia * PESOS_SCORE["autonomia"]
            + self.calidad_cortes * PESOS_SCORE["calidad_cortes"]
            + self.juicio_llm * PESOS_SCORE["juicio_llm"]
        )


class Episodio(Base):
    """Una entrega de la serie. Rango contiguo del fuente, en segundos absolutos."""

    indice: int = Field(ge=0)
    inicio: float = Field(ge=0)
    fin: float = Field(gt=0)
    titulo: str
    razon: str

    # --- formato serie; ausentes en el formato `virales` ---
    #: Número de entrega, 1-based. Invariante: `parte == indice + 1`.
    parte: int | None = Field(default=None, gt=0)
    total_partes: int | None = Field(default=None, gt=0)
    arco: Arco | None = None
    #: Qué ocurre en el episodio; materia prima del recap de la entrega siguiente.
    resumen: str | None = None
    #: Tensión que queda abierta al final y que resuelve el episodio siguiente.
    cliffhanger: str | None = None
    #: Segundos del fuente saltados desde el fin del episodio anterior (0 = encadenados).
    hueco_anterior: float = Field(default=0.0, ge=0)
    alineacion: AlineacionFronteras = Field(default_factory=AlineacionFronteras)
    score: ScoreEpisodio = Field(default_factory=ScoreEpisodio)

    #: True si el arco no lo leyó el modelo del material, sino que lo puso el código como
    #: proporción fija al detectar que el propuesto caía fuera del episodio.
    #:
    #: Importa porque el arco viaja al prompt del guion como «aquí está el pico de tensión»:
    #: afirmarlo cuando es `duracion * 0.62` es pedirle al guionista que respete un momento
    #: que puede caer en mitad de un silencio. Medido en la primera serie real: el desenlace
    #: estimado del episodio 2 cayó dentro de 92 s sin una sola palabra.
    arco_estimado: bool = False

    #: True si el código movió las fronteras después de que el modelo escribiera `resumen` y
    #: `cliffhanger`, de modo que esos textos describen material que ya no está dentro.
    #:
    #: En la primera serie real el episodio 2 se pidió como 345–1203 s y quedó truncado en
    #: 701; su resumen siguió hablando de escenas que se cayeron, y el caption anunciaba un
    #: final que no ocurre. Quien genere el guion debe regenerarlos en vez de heredarlos.
    metadatos_obsoletos: bool = False

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio

    @model_validator(mode="after")
    def _fin_despues_de_inicio(self) -> Episodio:
        if self.fin <= self.inicio:
            raise ValueError(f"episodio {self.indice}: fin ({self.fin}) <= inicio ({self.inicio})")
        return self


class Candidato(Base):
    """Un episodio propuesto que todavía no se ha decidido producir."""

    episodio: Episodio
    #: True si superó el filtro y entró en `serie.json`.
    seleccionado: bool = False
    #: Por qué se descartó, si se descartó. Auditable.
    motivo_descarte: str | None = None


class Candidatos(Base):
    """Todo lo que el sistema consideró, con su score. No todo se produce."""

    modelo: str
    formato: Formato = Formato.SERIE
    candidatos: list[Candidato] = Field(default_factory=list)

    def seleccionados(self) -> list[Candidato]:
        return [c for c in self.candidatos if c.seleccionado]


class Serie(Base):
    """`serie.json` — lo que se va a producir. Sustituye al `clips.json` del pipeline TS."""

    modelo: str
    formato: Formato = Formato.SERIE
    titulo: str = ""
    sinopsis: str = ""
    #: Fracción del fuente cubierta por los episodios: control de calidad y de riesgo legal.
    cobertura: float = Field(default=0.0, ge=0, le=1)
    episodios: list[Episodio] = Field(default_factory=list)

    #: Versión de prompt que decidió estos cortes. Ver `contratos.comunes.Procedencia`.
    procedencia: Procedencia | None = None

    @property
    def total_partes(self) -> int:
        return len(self.episodios)

    def por_indice(self, indice: int) -> Episodio | None:
        return next((e for e in self.episodios if e.indice == indice), None)
