"""Paso de guion: hook, reparto en tramos, caption y hashtags de un episodio.

En formato serie hay continuidad: cada episodio abre con un recap narrado de la entrega
anterior y cierra verbalizando la tensión que queda abierta. Ese recap **no** se deja a
criterio del modelo — el código lo inserta como primer tramo (`dominio.tramos.insertar_recap`),
para que la invariante se cumpla aunque el LLM lo ignore. Por eso el prompt le pide los tramos
a partir del segundo 8 en los episodios que llevan recap.

El texto de los prompts vive en `plantillas/guion.*.md`, no aquí: es lo que más se itera y
lo que menos tiene que ver con programar. Este módulo solo decide qué ramas condicionales
entran y con qué valores.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from viralfarm.dominio.tramos import (
    NARRACION_MAX,
    NARRACION_MIN,
    RECAP_SEG,
    TRAMO_NARRACION_MAX,
)
from viralfarm.prompts import plantillas


class TramoLlm(BaseModel):
    tipo: str = Field(description="'original' o 'narracion'")
    inicio: float = Field(description="Segundo de inicio dentro del episodio")
    fin: float = Field(description="Segundo de fin dentro del episodio")
    texto: str = Field(default="", description="Texto a narrar; vacío en tramos 'original'")


class RespuestaGuion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    hook: str = Field(description="Frase de gancho que se superpone al principio")
    recap: str = Field(default="", description="Voz en off que sitúa a quien llega nuevo")
    tramos: list[TramoLlm]
    resumen: str = Field(description="2-3 frases de lo que se cuenta en este episodio")
    cliffhanger: str = Field(description="Tensión que queda abierta al final")
    caption: str = Field(description="Texto de publicación, sin hashtags ni número de parte")
    hashtags: list[str] = Field(description="Hashtags sin el símbolo #")


@dataclass
class DatosGuion:
    idioma_salida: str
    palabras_por_segundo: float
    parte: int
    total_partes: int
    titulo_serie: str
    duracion: float
    #: Desde dónde empiezan los tramos del modelo: 0 en la parte 1, RECAP_SEG en el resto.
    desde: float
    max_original: float
    max_palabras_recap: int
    cumbre: float | None = None
    desenlace: float | None = None
    #: True si el arco lo puso el código como proporción fija, no el modelo leyendo el
    #: material. Cambia lo que se le dice al guionista: ver `_bloque_arco`.
    arco_estimado: bool = False


def _bloque_recap(d: DatosGuion) -> str:
    if d.parte == 1:
        return "1. RECAP: cadena vacía. Este es el primer episodio, no hay nada que recapitular."
    return "\n".join(
        [
            f"1. RECAP: {RECAP_SEG:.0f} segundos de voz en off que sitúan a quien llega nuevo y",
            "   retoman la tensión con la que cerró la entrega anterior. Empieza POR la tensión,",
            f"   no por el resumen. Máximo {d.max_palabras_recap} palabras. NO forma parte de tus",
            f"   `tramos`: el sistema lo coloca en los primeros {RECAP_SEG:.0f} segundos.",
        ]
    )


def _bloque_arco(d: DatosGuion) -> str:
    """Lo que se le dice al guionista sobre el pico de tensión.

    Si el arco lo estimó el código —una proporción fija, porque el propuesto caía fuera del
    episodio— **no se afirma que ahí esté el pico**. Afirmarlo hacía que el guionista
    protegiera un instante que podía caer en mitad de un silencio, y es justo lo que ocurrió
    en la primera serie real: el desenlace estimado del episodio 2 cayó dentro de 92 s sin
    una sola palabra.
    """
    if d.cumbre is None or d.desenlace is None:
        return ""
    if d.arco_estimado:
        return (
            "\n- No hay una lectura fiable de dónde está el pico de tensión de este episodio:"
            "\n  búscalo tú en el material y deja sonar el audio original ahí."
        )
    return "\n".join(
        [
            f"\n- Alrededor del segundo {d.cumbre:.0f} está el pico de tensión: deja sonar el",
            f"  material original ahí, no narres encima. Alrededor del {d.desenlace:.0f} se",
            "  cierra el arco.",
        ]
    )


def sistema(d: DatosGuion) -> str:
    """Instrucciones de cómo escribir el episodio. El texto vive en `guion.sistema.md`."""
    es_ultimo = d.parte == d.total_partes

    cierre = (
        "es el último episodio, así que aquí cierras la historia en vez de abrir nada."
        if es_ultimo
        else "la tensión que queda abierta al final, en una frase."
    )
    ultimo_tramo = (
        "cierra la historia y remite al perfil para ver la serie completa."
        if es_ultimo
        else "verbaliza la tensión que queda abierta y remite a la entrega siguiente. "
        "Nunca la resuelvas."
    )

    return plantillas.render(
        "guion.sistema",
        parte=d.parte,
        total_partes=d.total_partes,
        titulo_serie=d.titulo_serie,
        idioma_salida=d.idioma_salida,
        bloque_recap=_bloque_recap(d),
        desde=f"{d.desde:.0f}",
        duracion=f"{d.duracion:.1f}",
        cierre=cierre,
        ultimo_tramo=ultimo_tramo,
        bloque_arco=_bloque_arco(d),
        max_original=f"{d.max_original:.0f}",
        palabras_por_segundo=d.palabras_por_segundo,
        tramo_narracion_max=f"{TRAMO_NARRACION_MAX:.0f}",
        narracion_min=f"{NARRACION_MIN * 100:.0f}",
        narracion_max=f"{NARRACION_MAX * 100:.0f}",
    )


def version_sistema() -> str:
    return plantillas.version("guion.sistema")


def construir_prompt(
    d: DatosGuion,
    titulo: str,
    razon: str,
    transcripcion_episodio: str,
    idioma_origen: str,
    contexto_previo: str = "",
    traduce: bool = False,
) -> str:
    """Prompt de usuario. `transcripcion_episodio` debe venir de `recortar_a_episodio`.

    Esa procedencia importa: es lo que hace que el guionista vea los silencios del episodio
    y no solo las líneas de diálogo. Con la lista de solo-diálogo, un hueco de 58 segundos
    era invisible y se cubría con 4 segundos de voz.
    """
    aviso_traduccion = (
        f"El audio original está en {idioma_origen} y el público no lo entiende: apóyate más "
        'en tramos narrados y deja tramos "original" solo donde la imagen, la música o la '
        "emoción se expliquen sin palabras.\n\n"
        if traduce
        else ""
    )
    return plantillas.render(
        "guion.usuario",
        parte=d.parte,
        total_partes=d.total_partes,
        titulo=titulo,
        duracion=f"{d.duracion:.1f}",
        razon=razon,
        contexto_previo=contexto_previo,
        idioma_origen=idioma_origen,
        timeline=transcripcion_episodio or "(sin habla)",
        aviso_traduccion=aviso_traduccion,
        idioma_salida=d.idioma_salida,
        desde=f"{d.desde:.0f}",
    )


def version_usuario() -> str:
    return plantillas.version("guion.usuario")
