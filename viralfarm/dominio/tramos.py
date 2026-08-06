"""Reparto del episodio en tramos de narración y audio original.

Invariante que necesita el montaje: los tramos cubren el episodio **entero, en orden, sin
huecos ni solapes**. Este módulo la fuerza sobre lo que proponga el modelo, recortando el texto
que no quepa y partiendo la voz en off demasiado larga.

El recap que abre cada episodio desde el segundo lo inserta el código, no el modelo: así la
invariante se cumple aunque el LLM lo ignore.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from viralfarm.contratos.guion import TipoTramo, Tramo
from viralfarm.dominio.idiomas import Idioma

#: Margen libre al final de un tramo narrado para que la voz no pise el siguiente.
MARGEN = 0.3
#: Duración del recap que abre cada episodio a partir del segundo.
RECAP_SEG = 8.0
#: Más de esto de voz en off seguida tapa el material; el tramo se parte.
TRAMO_NARRACION_MAX = 20.0
#: Densidad de narración admisible: el suelo es transformatividad, el techo dejar respirar.
NARRACION_MIN = 0.4
NARRACION_MAX = 0.65
#: Por debajo de esto un tramo es residual y se absorbe en el anterior.
TRAMO_MINIMO = 0.5

_NUMERACION_PREVIA = re.compile(
    r"^(parte|part|partie|teil)\s*\d+\s*(?:/\s*\d+)?\s*[—\-:·]?\s*", re.I
)


@dataclass
class TramoPropuesto:
    tipo: TipoTramo
    inicio: float
    fin: float
    texto: str = ""


@dataclass
class ResultadoTramos:
    tramos: list[Tramo]
    avisos: list[str] = field(default_factory=list)


def contar_palabras(texto: str) -> int:
    return len([p for p in texto.strip().split() if p])


def recortar_a_palabras(texto: str, segundos: float, palabras_por_segundo: float) -> str:
    """Recorta el texto a lo que cabe hablando a ritmo natural en `segundos`."""
    maximo = max(1, int((segundos - MARGEN) * palabras_por_segundo))
    palabras = [p for p in texto.strip().split() if p]
    return " ".join(palabras[:maximo])


def normalizar_tramos(
    propuestos: Sequence[TramoPropuesto],
    desde: float,
    hasta: float,
    palabras_por_segundo: float,
) -> ResultadoTramos:
    """Encadena los tramos para que cubran exactamente `[desde, hasta]`.

    Recorta el texto narrado que no quepa y parte los tramos de voz demasiado largos: lo que
    sobra queda en audio original, que es preferible a una narración atropellada.
    """
    avisos: list[str] = []
    ordenados = sorted((t for t in propuestos if t.fin > t.inicio), key=lambda t: t.inicio)

    if not ordenados:
        return ResultadoTramos([Tramo(tipo=TipoTramo.ORIGINAL, inicio=desde, fin=hasta)], avisos)

    tramos: list[Tramo] = []
    cursor = desde

    for i, propuesto in enumerate(ordenados):
        es_ultimo = i == len(ordenados) - 1
        fin = hasta if es_ultimo else min(max(propuesto.fin, cursor), hasta)
        if fin - cursor < TRAMO_MINIMO:
            continue  # tramo residual: se absorbe en el anterior

        palabras = [p for p in propuesto.texto.strip().split() if p]
        if propuesto.tipo is TipoTramo.ORIGINAL or not palabras:
            tramos.append(Tramo(tipo=TipoTramo.ORIGINAL, inicio=cursor, fin=fin))
            cursor = fin
            continue

        # Voz en off demasiado larga: se narra el principio y el resto queda en audio original.
        fin_voz = min(fin, cursor + TRAMO_NARRACION_MAX)
        disponible = fin_voz - cursor - MARGEN
        max_palabras = max(1, int(disponible * palabras_por_segundo))
        if len(palabras) > max_palabras:
            avisos.append(
                f"tramo {cursor:.1f}–{fin_voz:.1f}s: narración recortada de {len(palabras)} "
                f"a {max_palabras} palabras para que quepa."
            )
        texto = " ".join(palabras[:max_palabras])

        tramos.append(Tramo(tipo=TipoTramo.NARRACION, inicio=cursor, fin=fin_voz, texto=texto))
        if fin - fin_voz >= TRAMO_MINIMO:
            tramos.append(Tramo(tipo=TipoTramo.ORIGINAL, inicio=fin_voz, fin=fin))
        cursor = fin

    if not tramos:
        return ResultadoTramos([Tramo(tipo=TipoTramo.ORIGINAL, inicio=desde, fin=hasta)], avisos)

    # El último tramo llega siempre al final exacto del episodio.
    tramos[-1] = tramos[-1].model_copy(update={"fin": hasta})
    return ResultadoTramos(tramos, avisos)


def insertar_recap(tramos: Sequence[Tramo], texto: str, palabras_por_segundo: float) -> list[Tramo]:
    """Antepone el recap narrado. Los tramos deben empezar ya en `RECAP_SEG`.

    Lo inserta el código y no el modelo para que la parte 2 en adelante SIEMPRE abra situando
    al espectador, aunque el LLM haya ignorado la instrucción.
    """
    recortado = recortar_a_palabras(texto, RECAP_SEG, palabras_por_segundo)
    if not recortado:
        raise ValueError("el recap no puede quedar vacío: revisa el contexto del episodio previo")
    return [
        Tramo(tipo=TipoTramo.NARRACION, inicio=0.0, fin=RECAP_SEG, texto=recortado),
        *tramos,
    ]


def max_palabras_recap(palabras_por_segundo: float) -> int:
    return int((RECAP_SEG - MARGEN) * palabras_por_segundo)


def evaluar_densidad(tramos: Sequence[Tramo], duracion: float) -> list[str]:
    """Avisos sobre cuánta voz en off lleva el episodio.

    Poca narración debilita el argumento de transformatividad (ver `riesgos.md`); demasiada
    tapa el material y el espectador se va.
    """
    avisos: list[str] = []
    if duracion <= 0:
        return avisos

    narrados = [t for t in tramos if t.tipo is TipoTramo.NARRACION]
    densidad = sum(t.duracion for t in narrados) / duracion

    if densidad < NARRACION_MIN:
        avisos.append(
            f"solo {densidad * 100:.0f} % narrado (mínimo {NARRACION_MIN * 100:.0f} %): "
            "poco aporte propio, ver docs/riesgos.md."
        )
    elif densidad > NARRACION_MAX:
        avisos.append(
            f"{densidad * 100:.0f} % narrado (máximo {NARRACION_MAX * 100:.0f} %): "
            "la voz en off tapa el material."
        )
    if tramos and tramos[-1].tipo is not TipoTramo.NARRACION:
        avisos.append("el episodio no cierra con voz en off; pierde el gancho.")
    return avisos


def componer_caption(
    texto: str,
    parte: int,
    total_partes: int,
    idioma: Idioma,
    cta: str = "",
    cta_final: str = "",
) -> str:
    """Numeración y llamada a la acción: las garantiza el código, no el modelo.

    Van en el idioma de salida, salvo que se pasen `cta`/`cta_final` explícitas.
    """
    # El modelo a veces numera por su cuenta pese a pedirle que no: se quita y se rehace.
    limpio = _NUMERACION_PREVIA.sub("", texto.strip())
    if parte < total_partes:
        llamada = cta or idioma.serie.cta
    else:
        llamada = cta_final or idioma.serie.cta_final
    return f"{idioma.serie.parte(parte, total_partes)} — {limpio}\n\n{llamada}"
