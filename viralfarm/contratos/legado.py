"""Lectura de los artefactos del pipeline TypeScript (Fase 1).

Existe por dos razones:

1. **Golden files.** Los artefactos ya producidos por el pipeline TS son la referencia contra
   la que se verifica que la reescritura en Python hace lo mismo (`docs/arquitectura.md` §9.4).
2. **Migración.** Un `workspace/` con trabajo a medias en formato antiguo se puede convertir sin
   volver a pagar transcripciones ni llamadas al LLM.

El formato TS usa camelCase y llama *clip* a lo que aquí es *episodio*. La conversión es pura:
no toca disco, recibe y devuelve estructuras.
"""

from __future__ import annotations

from typing import Any

from viralfarm.contratos.fuente import Fuente
from viralfarm.contratos.guion import Guion, TipoTramo, Tramo
from viralfarm.contratos.serie import (
    Alineacion,
    AlineacionFronteras,
    Arco,
    Episodio,
    Formato,
    ScoreEpisodio,
    Serie,
)
from viralfarm.contratos.voz import Voz, VozTramo


def fuente_desde_legado(datos: dict[str, Any]) -> Fuente:
    """`fuente.json` del pipeline TS (camelCase) → `Fuente`."""
    return Fuente(
        video_id=datos["videoId"],
        ruta_original=datos["rutaOriginal"],
        duracion=datos["duracion"],
        ancho=datos["ancho"],
        alto=datos["alto"],
        fps=datos["fps"],
        rotacion=datos.get("rotacion", 0),
        codec_video=datos["codecVideo"],
        codec_audio=datos.get("codecAudio"),
        creado_en=datos["creadoEn"],
    )


def _episodio_desde_legado(clip: dict[str, Any]) -> Episodio:
    arco = clip.get("arco")
    alineacion = clip.get("alineacion") or {}
    # `puntuacion` del TS era 0-10 y la ponía el modelo. Aquí es UNA señal más dentro del score
    # desglosado, normalizada a [0, 1]; los demás componentes no existían y quedan a 0.
    juicio = max(0.0, min(10.0, float(clip.get("puntuacion", 0)))) / 10.0
    return Episodio(
        indice=clip["indice"],
        inicio=clip["inicio"],
        fin=clip["fin"],
        titulo=clip["titulo"],
        razon=clip["razon"],
        parte=clip.get("parte"),
        total_partes=clip.get("totalPartes"),
        arco=Arco(cumbre=arco["cumbre"], desenlace=arco["desenlace"]) if arco else None,
        resumen=clip.get("resumen"),
        cliffhanger=clip.get("cliffhanger"),
        hueco_anterior=clip.get("huecoAnterior", 0.0) or 0.0,
        alineacion=AlineacionFronteras(
            inicio=Alineacion(alineacion.get("inicio", "llm")),
            fin=Alineacion(alineacion.get("fin", "llm")),
        ),
        score=ScoreEpisodio(juicio_llm=juicio),
    )


def serie_desde_legado(datos: dict[str, Any]) -> Serie:
    """`clips.json` del pipeline TS → `Serie`."""
    serie = datos.get("serie") or {}
    return Serie(
        modelo=datos["modelo"],
        formato=Formato(datos.get("formato", "virales")),
        titulo=serie.get("titulo", ""),
        sinopsis=serie.get("sinopsis", ""),
        cobertura=serie.get("cobertura", 0.0),
        episodios=[_episodio_desde_legado(c) for c in datos.get("clips", [])],
    )


def guion_desde_legado(datos: dict[str, Any]) -> Guion:
    """`clips/<n>/guion.json` del pipeline TS → `Guion`."""
    return Guion(
        indice=datos["indice"],
        idioma=datos.get("idioma", "es"),
        hook=datos["hook"],
        tramos=[
            Tramo(
                tipo=TipoTramo(t["tipo"]),
                inicio=t["inicio"],
                fin=t["fin"],
                texto=t.get("texto") or "",
            )
            for t in datos["tramos"]
        ],
        caption=datos.get("caption", ""),
        hashtags=datos.get("hashtags", []),
        parte=datos.get("parte"),
        total_partes=datos.get("totalPartes"),
        recap=datos.get("recap") or "",
        resumen=datos.get("resumen") or "",
        cliffhanger=datos.get("cliffhanger") or "",
    )


def voz_desde_legado(datos: dict[str, Any]) -> Voz:
    """`clips/<n>/narracion.json` del pipeline TS → `Voz`."""
    return Voz(
        voz=datos["voz"],
        tramos=[
            VozTramo(
                tramo=t["tramo"],
                archivo=t["archivo"],
                desplazamiento=t["desplazamiento"],
                duracion=t["duracion"],
                tempo=t.get("tempo", 1.0),
                palabras=t.get("palabras", []),
            )
            for t in datos["tramos"]
        ],
    )
