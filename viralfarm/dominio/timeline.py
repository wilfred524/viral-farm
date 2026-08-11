"""Construcción de la línea de tiempo multimodal.

Fusiona diálogo, silencios y —cuando exista— acciones vistas, en una sola secuencia ordenada.
Es el contrato de entrada del paso de selección de episodios.

Su razón de ser es arquitectónica: mientras el prompt se construía directamente desde la
transcripción, añadir percepción visual obligaba a tocar el paso de selección. Con la línea de
tiempo como artefacto intermedio, la capa de visión se enchufa sin tocar nada aguas abajo (ver
`docs/arquitectura.md` §6.2).
"""

from __future__ import annotations

from collections.abc import Sequence

from viralfarm.contratos.timeline import EventoTimeline, Timeline, TipoEvento
from viralfarm.contratos.transcripcion import Transcripcion
from viralfarm.contratos.vision import Observacion, Vision
from viralfarm.dominio.episodios import SILENCIO_NOTABLE

#: Duración que se atribuye a una observación visual puntual, en segundos.
DURACION_OBSERVACION = 2.0

#: Hueco sin habla que se marca al escribir el guion de UN episodio.
#:
#: Mucho más fino que `SILENCIO_NOTABLE` (15 s), que es el umbral para elegir cortes en una
#: película entera. Dentro de un episodio de seis minutos, 15 s es demasiado grueso: en la
#: primera serie real el guionista no vio un hueco de 58 s porque nadie se lo dijo, y lo
#: cubrió con un tramo de 4,1 s de voz.
SILENCIO_EN_EPISODIO = 6.0


def recortar_a_episodio(
    timeline: Timeline, inicio: float, fin: float, silencio_notable: float = SILENCIO_EN_EPISODIO
) -> Timeline:
    """Porción de la línea de tiempo dentro de `[inicio, fin]`, con tiempos relativos.

    Los silencios se recalculan sobre el recorte: un hueco que en la película entera no
    llegaba al umbral puede ser enorme dentro de un episodio, y es justo el que el guionista
    necesita ver para decidir si narra ahí o deja respirar.
    """
    dentro = [
        EventoTimeline(
            tipo=e.tipo,
            inicio=max(0.0, e.inicio - inicio),
            fin=min(fin, e.fin) - inicio,
            texto=e.texto,
            intensidad=e.intensidad,
        )
        for e in timeline.eventos
        if e.tipo is not TipoEvento.SILENCIO and e.fin > inicio and e.inicio < fin
    ]

    duracion = fin - inicio
    con_silencios: list[EventoTimeline] = []
    anterior = 0.0
    for evento in sorted(dentro, key=lambda e: e.inicio):
        hueco = evento.inicio - anterior
        if hueco >= silencio_notable:
            con_silencios.append(
                EventoTimeline(
                    tipo=TipoEvento.SILENCIO,
                    inicio=anterior,
                    fin=evento.inicio,
                    texto=f"sin diálogo · {hueco:.0f} s",
                )
            )
        con_silencios.append(evento)
        anterior = max(anterior, evento.fin)

    cola = duracion - anterior
    if cola >= silencio_notable:
        con_silencios.append(
            EventoTimeline(
                tipo=TipoEvento.SILENCIO,
                inicio=anterior,
                fin=duracion,
                texto=f"sin diálogo · {cola:.0f} s",
            )
        )

    return Timeline(
        duracion=duracion,
        idioma=timeline.idioma,
        con_vision=timeline.con_vision,
        eventos=con_silencios,
    )


def construir_timeline(
    transcripcion: Transcripcion,
    duracion_fuente: float,
    vision: Vision | None = None,
    silencio_notable: float = SILENCIO_NOTABLE,
) -> Timeline:
    """Fusiona las fuentes disponibles en una secuencia ordenada por tiempo.

    Los silencios se marcan explícitamente: sin ellos el modelo solo ve diálogo y es ciego a la
    mitad no hablada de una película — justo donde suele estar el relleno que se le pide
    detectar.
    """
    eventos: list[EventoTimeline] = []
    anterior = 0.0

    for segmento in transcripcion.segmentos:
        hueco = segmento.inicio - anterior
        if hueco >= silencio_notable:
            eventos.append(
                EventoTimeline(
                    tipo=TipoEvento.SILENCIO,
                    inicio=anterior,
                    fin=segmento.inicio,
                    texto=f"sin diálogo · {hueco:.0f} s",
                )
            )
        if segmento.fin > segmento.inicio:
            eventos.append(
                EventoTimeline(
                    tipo=TipoEvento.DIALOGO,
                    inicio=segmento.inicio,
                    fin=segmento.fin,
                    texto=segmento.texto,
                )
            )
        anterior = max(anterior, segmento.fin)

    cola = duracion_fuente - anterior
    if cola >= silencio_notable:
        eventos.append(
            EventoTimeline(
                tipo=TipoEvento.SILENCIO,
                inicio=anterior,
                fin=duracion_fuente,
                texto=f"sin diálogo · {cola:.0f} s",
            )
        )

    if vision is not None:
        eventos.extend(_eventos_de_vision(vision.observaciones, duracion_fuente))

    eventos.sort(key=lambda e: (e.inicio, e.tipo))
    return Timeline(
        duracion=duracion_fuente,
        idioma=transcripcion.idioma,
        con_vision=vision is not None,
        eventos=eventos,
    )


def _eventos_de_vision(
    observaciones: Sequence[Observacion], duracion_fuente: float
) -> list[EventoTimeline]:
    eventos: list[EventoTimeline] = []
    for observacion in observaciones:
        tiempo = float(observacion.tiempo)
        fin = min(duracion_fuente, tiempo + DURACION_OBSERVACION)
        if fin <= tiempo:
            continue
        intensidad = observacion.intensidad / 10.0
        eventos.append(
            EventoTimeline(
                tipo=TipoEvento.ACCION,
                inicio=tiempo,
                fin=fin,
                texto=observacion.accion,
                intensidad=max(0.0, min(1.0, intensidad)),
            )
        )
    return eventos


def formatear_para_prompt(timeline: Timeline) -> str:
    """Representación textual que se le pasa al modelo.

    Cada tipo de evento va marcado para que el modelo distinga lo que se dice, lo que se ve y
    lo que no suena.
    """
    marca = {
        TipoEvento.DIALOGO: "",
        TipoEvento.SILENCIO: "«{}»",
        TipoEvento.ACCION: "▸ {}",
    }
    lineas = []
    for evento in timeline.eventos:
        plantilla = marca[evento.tipo]
        texto = plantilla.format(evento.texto) if plantilla else evento.texto
        lineas.append(f"[{evento.inicio:.1f}–{evento.fin:.1f}] {texto}")
    return "\n".join(lineas)
