"""Construcción de la pista de subtítulos del episodio.

Dos orígenes, en tiempos relativos al inicio del episodio:

- tramos `original`: las palabras del audio del material, tomadas de la transcripción.
- tramos `narracion`: las palabras de la voz generada, con los timings que devolvió el TTS.

Estaba enterrado en el paso de render del pipeline TypeScript, donde no había forma de
verificarlo sin renderizar.
"""

from __future__ import annotations

from collections.abc import Sequence

from viralfarm.contratos.comunes import Segmento
from viralfarm.contratos.guion import Guion, TipoTramo
from viralfarm.contratos.subtitulos import OrigenSubtitulo, Subtitulo
from viralfarm.contratos.voz import Voz

#: Palabras por línea: suficiente para leer de un vistazo sin tapar la imagen.
PALABRAS_POR_LINEA = 4


def construir_subtitulos(
    guion: Guion,
    segmentos: Sequence[Segmento],
    voz: Voz | None,
    inicio_episodio: float,
) -> list[Subtitulo]:
    """Pista completa del episodio, ordenada por tiempo.

    `inicio_episodio` es el segundo absoluto del fuente donde arranca el episodio: sirve para
    pasar los tiempos de la transcripción a relativos.
    """
    subtitulos: list[Subtitulo] = []

    for posicion, tramo in enumerate(guion.tramos):
        if tramo.tipo is TipoTramo.ORIGINAL:
            for segmento in segmentos:
                for palabra in segmento.palabras:
                    relativo = palabra.inicio - inicio_episodio
                    if relativo < tramo.inicio or relativo >= tramo.fin:
                        continue
                    subtitulos.append(
                        Subtitulo(
                            texto=palabra.texto,
                            inicio=relativo,
                            fin=palabra.fin - inicio_episodio,
                            origen=OrigenSubtitulo.ORIGINAL,
                        )
                    )
            continue

        pista = voz.por_tramo(posicion) if voz else None
        if pista is None:
            continue
        for palabra in pista.palabras:
            subtitulos.append(
                Subtitulo(
                    texto=palabra.texto,
                    inicio=pista.desplazamiento + palabra.inicio,
                    fin=pista.desplazamiento + palabra.fin,
                    origen=OrigenSubtitulo.NARRACION,
                )
            )

    return sorted(subtitulos, key=lambda s: s.inicio)


def agrupar_en_lineas(
    subtitulos: Sequence[Subtitulo], por_linea: int = PALABRAS_POR_LINEA
) -> list[list[Subtitulo]]:
    """Agrupa las palabras en líneas de pantalla.

    Nunca mezcla orígenes en la misma línea: una línea que empieza en audio original y termina
    en voz en off cambiaría de color a media frase.
    """
    lineas: list[list[Subtitulo]] = []
    actual: list[Subtitulo] = []

    for palabra in subtitulos:
        if actual and (len(actual) >= por_linea or actual[0].origen != palabra.origen):
            lineas.append(actual)
            actual = []
        actual.append(palabra)

    if actual:
        lineas.append(actual)
    return lineas
