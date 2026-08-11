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
from viralfarm.contratos.voz import Voz
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

#: Fracción del tramo narrado que la voz debe ocupar para que el tramo no suene vacío.
#:
#: La densidad se medía sobre el tramo ASIGNADO, no sobre el audio que suena, así que el
#: sistema no sabía lo vacío que estaba su propio resultado: en la primera serie real
#: declaró 38 % y 27 % de narración cuando la voz real ocupaba el 13,3 % y el 19,0 %. Un
#: tramo de 16,4 s llegó a contener 4,1 s de voz — doce segundos de nada.
OCUPACION_MINIMA_VOZ = 0.7

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


def segundos_de_voz(voz: Voz | None) -> float:
    """Segundos de audio narrado que realmente suenan. `None` = todavía no se sintetizó."""
    return sum(t.duracion for t in voz.tramos) if voz else 0.0


def densidad_real(tramos: Sequence[Tramo], duracion: float, voz: Voz | None) -> float:
    """Fracción del episodio con voz en off **sonando**, en [0, 1].

    Con `voz`, mide el audio sintetizado. Sin ella, cae a la duración de los tramos
    asignados, que es una cota superior: sirve para validar el guion antes del TTS, pero no
    debe confundirse con lo que el espectador oirá.
    """
    if duracion <= 0:
        return 0.0
    if voz is not None:
        return segundos_de_voz(voz) / duracion
    return sum(t.duracion for t in tramos if t.tipo is TipoTramo.NARRACION) / duracion


def detectar_aire_muerto(
    tramos: Sequence[Tramo], voz: Voz, ocupacion_minima: float = OCUPACION_MINIMA_VOZ
) -> list[str]:
    """Tramos narrados cuya voz no llena el hueco que se les asignó.

    Es diagnóstico, no corrección: qué hacer con un hueco —alargar el texto, acortar el
    tramo o dejar respirar el material— es una decisión narrativa, no mecánica.
    """
    avisos: list[str] = []
    for posicion, tramo in enumerate(tramos):
        if tramo.tipo is not TipoTramo.NARRACION or tramo.duracion <= 0:
            continue
        pista = voz.por_tramo(posicion)
        if pista is None:
            avisos.append(
                f"tramo {posicion} ({tramo.inicio:.1f}–{tramo.fin:.1f}s): narrado pero sin "
                "audio sintetizado; sonará mudo."
            )
            continue
        ocupacion = pista.duracion / tramo.duracion
        if ocupacion < ocupacion_minima:
            avisos.append(
                f"tramo {posicion} ({tramo.inicio:.1f}–{tramo.fin:.1f}s): "
                f"{pista.duracion:.1f}s de voz en {tramo.duracion:.1f}s de tramo "
                f"({ocupacion * 100:.0f}%): {tramo.duracion - pista.duracion:.1f}s de silencio "
                "dentro de un tramo que se cuenta como narrado."
            )
    return avisos


def evaluar_densidad(
    tramos: Sequence[Tramo], duracion: float, voz: Voz | None = None
) -> list[str]:
    """Avisos sobre cuánta voz en off lleva el episodio.

    Poca narración debilita el argumento de transformatividad (ver `riesgos.md`); demasiada
    tapa el material y el espectador se va.

    Con `voz` mide el audio real y añade el desglose de aire muerto. Sin ella mide los
    tramos asignados y **lo dice**, para que un 38 % optimista no se confunda con la
    realidad.
    """
    avisos: list[str] = []
    if duracion <= 0:
        return avisos

    narrados = [t for t in tramos if t.tipo is TipoTramo.NARRACION]
    densidad = densidad_real(tramos, duracion, voz)

    if voz is not None:
        asignada = sum(t.duracion for t in narrados) / duracion
        if asignada - densidad > 0.05:
            avisos.append(
                f"narración real {densidad * 100:.0f} % frente al {asignada * 100:.0f} % "
                f"asignado: {sum(t.duracion for t in narrados) - segundos_de_voz(voz):.0f}s "
                "de los tramos narrados están en silencio."
            )
        avisos.extend(detectar_aire_muerto(tramos, voz))
    elif narrados:
        avisos.append(
            "densidad medida sobre los tramos asignados, no sobre el audio: el valor real "
            "solo se conoce tras sintetizar la voz."
        )

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
