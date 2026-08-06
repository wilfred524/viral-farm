"""Los artefactos reales del pipeline TypeScript validan contra los contratos Pydantic.

Es el primer criterio de aceptación de la migración: si un artefacto ya producido no valida, el
contrato está mal, no el artefacto.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import necesita_golden
from viralfarm.contratos import Transcripcion
from viralfarm.contratos.legado import (
    fuente_desde_legado,
    guion_desde_legado,
    serie_desde_legado,
    voz_desde_legado,
)
from viralfarm.contratos.serie import Formato

pytestmark = [pytest.mark.golden, necesita_golden]


def test_transcripcion_valida_sin_conversion(transcripcion_legado: dict[str, Any]) -> None:
    """`transcripcion.json` ya usa los mismos nombres: valida tal cual."""
    transcripcion = Transcripcion.model_validate(transcripcion_legado)
    assert transcripcion.segmentos
    assert transcripcion.total_palabras() > 0
    assert transcripcion.idioma


def test_fuente_convierte_desde_camelcase(fuente_legado: dict[str, Any]) -> None:
    fuente = fuente_desde_legado(fuente_legado)
    assert fuente.video_id
    assert fuente.duracion > 0
    assert fuente.fps > 0
    assert fuente.codec_audio, "sin pista de audio no hay transcripción posible"


def test_serie_convierte_y_conserva_los_episodios(clips_legado: dict[str, Any]) -> None:
    serie = serie_desde_legado(clips_legado)
    assert serie.formato is Formato.SERIE
    assert len(serie.episodios) == len(clips_legado["clips"])
    assert serie.total_partes == len(serie.episodios)
    assert serie.titulo

    for episodio, original in zip(serie.episodios, clips_legado["clips"], strict=True):
        assert episodio.inicio == original["inicio"]
        assert episodio.fin == original["fin"]
        assert episodio.parte == original["parte"]
        # La puntuación 0-10 del modelo pasa a ser una señal más dentro del score desglosado.
        assert episodio.score.juicio_llm == pytest.approx(original["puntuacion"] / 10)


def test_episodios_del_golden_cumplen_las_invariantes(clips_legado: dict[str, Any]) -> None:
    """Lo que produjo el pipeline TS respeta las reglas que el dominio impone."""
    from viralfarm.dominio.episodios import DURACION_MAX, DURACION_MIN

    serie = serie_desde_legado(clips_legado)
    for i, episodio in enumerate(serie.episodios):
        assert DURACION_MIN <= episodio.duracion <= DURACION_MAX
        assert episodio.parte == i + 1
        assert episodio.total_partes == len(serie.episodios)
        if i > 0:
            assert episodio.inicio >= serie.episodios[i - 1].fin


def test_cobertura_del_golden_respeta_el_limite(clips_legado: dict[str, Any]) -> None:
    from viralfarm.dominio.episodios import COBERTURA_MAX

    assert clips_legado["serie"]["cobertura"] <= COBERTURA_MAX


def test_guiones_validan_y_los_tramos_estan_encadenados(
    guiones_legado: list[dict[str, Any]],
) -> None:
    assert guiones_legado, "no hay guiones en los artefactos de referencia"
    for datos in guiones_legado:
        # El validador del contrato falla si hay huecos o solapes entre tramos.
        guion = guion_desde_legado(datos)
        assert guion.hook
        assert guion.tramos
        assert guion.tramos[0].inicio == 0, "los tramos deben cubrir el episodio desde 0"


def test_guiones_del_golden_empiezan_por_recap_desde_la_parte_2(
    guiones_legado: list[dict[str, Any]],
) -> None:
    from viralfarm.contratos.guion import TipoTramo
    from viralfarm.dominio.tramos import RECAP_SEG

    for datos in guiones_legado:
        guion = guion_desde_legado(datos)
        if guion.parte is None or guion.parte == 1:
            continue
        primero = guion.tramos[0]
        assert primero.tipo is TipoTramo.NARRACION
        assert primero.fin == pytest.approx(RECAP_SEG)
        assert primero.texto.strip()


def test_voz_convierte_y_los_tramos_apuntan_a_tramos_del_guion(
    narraciones_legado: list[dict[str, Any]],
    guiones_legado: list[dict[str, Any]],
) -> None:
    if not narraciones_legado:
        pytest.skip("no hay narraciones sintetizadas en los artefactos de referencia")

    for datos, datos_guion in zip(narraciones_legado, guiones_legado, strict=False):
        voz = voz_desde_legado(datos)
        guion = guion_desde_legado(datos_guion)
        assert voz.voz
        for pista in voz.tramos:
            assert 0 <= pista.tramo < len(guion.tramos)
            assert guion.tramos[pista.tramo].tipo.value == "narracion"
