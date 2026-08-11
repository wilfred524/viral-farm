"""Ensamblado del guion: de lo que responde el modelo al artefacto que consume el montaje.

Aquí está la mitad de «el LLM propone, el código verifica y repara» que corresponde al guion.
El modelo devuelve tramos con tiempos aproximados y textos de longitud libre; este módulo los
convierte en la invariante que el montaje necesita —tramos encadenados que cubren el episodio
entero, recap garantizado en las entregas 2+, caption numerado— y devuelve los avisos de lo
que tuvo que corregir.

Es dominio puro: sin disco, sin red, sin config. El paso que lo invoca aporta la respuesta del
modelo y la procedencia; qué hacer con los avisos es decisión de quien lo llame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from viralfarm.contratos.comunes import Procedencia
from viralfarm.contratos.guion import Guion, TipoTramo
from viralfarm.contratos.serie import Episodio
from viralfarm.dominio.idiomas import Idioma
from viralfarm.dominio.tramos import (
    RECAP_SEG,
    TramoPropuesto,
    componer_caption,
    evaluar_densidad,
    insertar_recap,
    normalizar_tramos,
)
from viralfarm.prompts.guion import RespuestaGuion


@dataclass
class ResultadoGuion:
    guion: Guion
    avisos: list[str] = field(default_factory=list)


def _tipo(bruto: str) -> TipoTramo:
    """El modelo escribe el tipo como texto libre; cualquier cosa que no sea narración es
    audio original, que es la opción segura: dejar sonar la película nunca rompe nada."""
    return TipoTramo.NARRACION if bruto.strip().lower().startswith("narr") else TipoTramo.ORIGINAL


def ensamblar(
    respuesta: RespuestaGuion,
    episodio: Episodio,
    idioma: Idioma,
    total_partes: int,
    procedencia: Procedencia | None = None,
) -> ResultadoGuion:
    """Guion validado a partir de la respuesta del modelo.

    El recap **no** sale de los tramos del modelo: se le pide aparte y lo coloca el código en
    los primeros `RECAP_SEG` segundos, para que la entrega 2 en adelante siempre abra situando
    al espectador aunque el LLM ignore la instrucción.
    """
    parte = episodio.parte or episodio.indice + 1
    desde = RECAP_SEG if parte > 1 else 0.0

    normalizados = normalizar_tramos(
        [
            TramoPropuesto(tipo=_tipo(t.tipo), inicio=t.inicio, fin=t.fin, texto=t.texto)
            for t in respuesta.tramos
        ],
        desde=desde,
        hasta=episodio.duracion,
        palabras_por_segundo=idioma.palabras_por_segundo,
    )
    avisos = list(normalizados.avisos)
    tramos = normalizados.tramos

    if parte > 1:
        if not respuesta.recap.strip():
            avisos.append(
                f"parte {parte}: el modelo no devolvió recap; se reutiliza el resumen previo."
            )
        tramos = insertar_recap(
            tramos,
            respuesta.recap.strip() or respuesta.resumen,
            idioma.palabras_por_segundo,
        )

    guion = Guion(
        indice=episodio.indice,
        idioma=idioma.codigo,
        hook=respuesta.hook.strip(),
        tramos=tramos,
        caption=componer_caption(respuesta.caption, parte, total_partes, idioma),
        hashtags=[h.lstrip("#").strip() for h in respuesta.hashtags if h.strip()],
        parte=parte,
        total_partes=total_partes,
        recap=tramos[0].texto if parte > 1 else "",
        resumen=respuesta.resumen.strip(),
        cliffhanger=respuesta.cliffhanger.strip(),
        procedencia=procedencia,
    )

    avisos += evaluar_densidad(guion.tramos, guion.duracion)
    return ResultadoGuion(guion, avisos)
