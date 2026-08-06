"""Reparto en tramos: la invariante que necesita el montaje."""

from __future__ import annotations

from itertools import pairwise

import pytest

from viralfarm.contratos.guion import TipoTramo
from viralfarm.dominio.idiomas import resolver_idioma
from viralfarm.dominio.tramos import (
    NARRACION_MAX,
    NARRACION_MIN,
    RECAP_SEG,
    TRAMO_NARRACION_MAX,
    TramoPropuesto,
    componer_caption,
    contar_palabras,
    evaluar_densidad,
    insertar_recap,
    max_palabras_recap,
    normalizar_tramos,
    recortar_a_palabras,
)

PPS = 2.6  # palabras por segundo del español


def narracion(inicio: float, fin: float, texto: str) -> TramoPropuesto:
    return TramoPropuesto(tipo=TipoTramo.NARRACION, inicio=inicio, fin=fin, texto=texto)


def original(inicio: float, fin: float) -> TramoPropuesto:
    return TramoPropuesto(tipo=TipoTramo.ORIGINAL, inicio=inicio, fin=fin)


def assert_encadenados(tramos: list, desde: float, hasta: float) -> None:
    """La invariante completa: cubren [desde, hasta], en orden, sin huecos ni solapes."""
    assert tramos, "no puede quedar sin tramos"
    assert tramos[0].inicio == pytest.approx(desde)
    assert tramos[-1].fin == pytest.approx(hasta)
    for anterior, siguiente in pairwise(tramos):
        assert siguiente.inicio == pytest.approx(anterior.fin)


# --- normalización ---------------------------------------------------------


def test_tramos_correctos_cubren_el_episodio() -> None:
    resultado = normalizar_tramos(
        [narracion(0, 10, "hola que tal"), original(10, 30), narracion(30, 40, "adios")],
        0,
        40,
        PPS,
    )
    assert_encadenados(resultado.tramos, 0, 40)
    assert not resultado.avisos


def test_sin_propuestas_queda_audio_original_entero() -> None:
    resultado = normalizar_tramos([], 0, 60, PPS)
    assert len(resultado.tramos) == 1
    assert resultado.tramos[0].tipo is TipoTramo.ORIGINAL
    assert_encadenados(resultado.tramos, 0, 60)


def test_hueco_entre_propuestas_se_cierra() -> None:
    """El modelo deja un hueco de 10 s; el montaje no lo toleraría."""
    resultado = normalizar_tramos([original(0, 20), original(30, 60)], 0, 60, PPS)
    assert_encadenados(resultado.tramos, 0, 60)


def test_solape_entre_propuestas_se_cierra() -> None:
    resultado = normalizar_tramos([original(0, 40), original(20, 60)], 0, 60, PPS)
    assert_encadenados(resultado.tramos, 0, 60)


def test_texto_que_no_cabe_se_recorta_y_avisa() -> None:
    largo = " ".join(["palabra"] * 100)
    resultado = normalizar_tramos([narracion(0, 10, largo)], 0, 10, PPS)
    narrado = resultado.tramos[0]
    assert narrado.tipo is TipoTramo.NARRACION
    assert contar_palabras(narrado.texto) <= int((10 - 0.3) * PPS)
    assert any("recortada" in aviso for aviso in resultado.avisos)


def test_voz_demasiado_larga_se_parte_y_el_resto_queda_original() -> None:
    resultado = normalizar_tramos([narracion(0, 60, "hola " * 50)], 0, 60, PPS)
    assert resultado.tramos[0].tipo is TipoTramo.NARRACION
    assert resultado.tramos[0].duracion == pytest.approx(TRAMO_NARRACION_MAX)
    assert resultado.tramos[1].tipo is TipoTramo.ORIGINAL
    assert_encadenados(resultado.tramos, 0, 60)


def test_tramo_narracion_sin_texto_se_convierte_en_original() -> None:
    resultado = normalizar_tramos([narracion(0, 30, "   ")], 0, 30, PPS)
    assert resultado.tramos[0].tipo is TipoTramo.ORIGINAL


def test_tramo_residual_se_absorbe() -> None:
    resultado = normalizar_tramos(
        [original(0, 30), original(30, 30.2), original(30.2, 60)], 0, 60, PPS
    )
    assert_encadenados(resultado.tramos, 0, 60)
    assert all(t.duracion >= 0.5 for t in resultado.tramos)


def test_desde_distinto_de_cero_para_dejar_sitio_al_recap() -> None:
    resultado = normalizar_tramos(
        [original(RECAP_SEG, 100)], RECAP_SEG, 100, PPS
    )
    assert_encadenados(resultado.tramos, RECAP_SEG, 100)


# --- recap -----------------------------------------------------------------


def test_insertar_recap_abre_el_episodio() -> None:
    resultado = normalizar_tramos([original(RECAP_SEG, 100)], RECAP_SEG, 100, PPS)
    con_recap = insertar_recap(resultado.tramos, "lo que pasó antes", PPS)
    assert con_recap[0].tipo is TipoTramo.NARRACION
    assert con_recap[0].inicio == 0
    assert con_recap[0].fin == RECAP_SEG
    assert_encadenados(con_recap, 0, 100)


def test_recap_se_recorta_a_lo_que_cabe_en_ocho_segundos() -> None:
    tramos = normalizar_tramos([original(RECAP_SEG, 100)], RECAP_SEG, 100, PPS).tramos
    con_recap = insertar_recap(tramos, " ".join(["palabra"] * 200), PPS)
    assert contar_palabras(con_recap[0].texto) <= max_palabras_recap(PPS)


def test_recap_vacio_es_error() -> None:
    with pytest.raises(ValueError, match="recap"):
        insertar_recap([], "   ", PPS)


def test_recortar_a_palabras_respeta_el_margen() -> None:
    texto = " ".join(["uno"] * 50)
    recortado = recortar_a_palabras(texto, 10, PPS)
    assert contar_palabras(recortado) == int((10 - 0.3) * PPS)


def test_recortar_no_alarga_un_texto_corto() -> None:
    assert recortar_a_palabras("dos palabras", 10, PPS) == "dos palabras"


# --- densidad --------------------------------------------------------------


def test_densidad_en_rango_no_avisa() -> None:
    objetivo = (NARRACION_MIN + NARRACION_MAX) / 2
    fin_voz = 100 * objetivo
    tramos = normalizar_tramos(
        [narracion(0, fin_voz, "hola " * 5), original(fin_voz, 90), narracion(90, 100, "fin")],
        0,
        100,
        PPS,
    ).tramos
    # El último tramo es narración, así que no debe avisar de cierre sin voz.
    assert not any("gancho" in aviso for aviso in evaluar_densidad(tramos, 100))


def test_poca_narracion_avisa_por_transformatividad() -> None:
    tramos = normalizar_tramos([original(0, 95), narracion(95, 100, "fin")], 0, 100, PPS).tramos
    avisos = evaluar_densidad(tramos, 100)
    assert any("mínimo" in aviso for aviso in avisos)


def test_demasiada_narracion_avisa_por_tapar_el_material() -> None:
    tramos = normalizar_tramos(
        [narracion(i * 10, i * 10 + 10, "hola " * 3) for i in range(10)], 0, 100, PPS
    ).tramos
    avisos = evaluar_densidad(tramos, 100)
    assert any("máximo" in aviso for aviso in avisos)


def test_cierre_sin_voz_en_off_avisa() -> None:
    tramos = normalizar_tramos(
        [narracion(0, 50, "hola " * 20), original(50, 100)], 0, 100, PPS
    ).tramos
    assert any("gancho" in aviso for aviso in evaluar_densidad(tramos, 100))


# --- caption ---------------------------------------------------------------


def test_caption_lleva_numeracion_y_cta_del_idioma() -> None:
    caption = componer_caption("Un thriller olvidado", 2, 8, resolver_idioma("es"))
    assert caption.startswith("Parte 2/8 — Un thriller olvidado")
    assert "Sígueme" in caption


def test_caption_del_ultimo_episodio_usa_el_cta_final() -> None:
    idioma = resolver_idioma("es")
    caption = componer_caption("El final", 8, 8, idioma)
    assert idioma.serie.cta_final in caption


def test_caption_quita_la_numeracion_que_puso_el_modelo() -> None:
    caption = componer_caption("Parte 3/8 — El giro", 3, 8, resolver_idioma("es"))
    assert caption.count("Parte 3/8") == 1
    assert "El giro" in caption


def test_caption_respeta_una_cta_personalizada() -> None:
    caption = componer_caption("Algo", 1, 5, resolver_idioma("es"), cta="Dale follow")
    assert "Dale follow" in caption
    assert "Sígueme" not in caption


def test_caption_en_ingles_no_mezcla_idiomas() -> None:
    caption = componer_caption("A forgotten thriller", 2, 8, resolver_idioma("en"))
    assert caption.startswith("Part 2/8")
    assert "Follow" in caption
    assert "Sígueme" not in caption
