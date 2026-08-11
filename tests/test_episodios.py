"""Normalización y reparación de la serie.

Es la lógica más frágil del sistema y la que en TypeScript solo se podía verificar
renderizando: el LLM propone tiempos y aquí se decide qué se repara, qué se fusiona y qué
rompe la serie entera.
"""

from __future__ import annotations

import pytest

from viralfarm.contratos.comunes import Palabra, Segmento
from viralfarm.contratos.serie import Alineacion, AlineacionFronteras
from viralfarm.dominio.episodios import (
    COBERTURA_MAX,
    DURACION_MAX,
    DURACION_MIN,
    EpisodioPropuesto,
    SerieInvalida,
    ajustar_a_frontera,
    alinear_corte,
    calcular_cobertura,
    calidad_de_cortes,
    normalizar_episodios,
    parte_una_palabra,
)


def segmentos_cada(paso: float, hasta: float) -> list[Segmento]:
    """Transcripción sintética: un segmento hablado por cada `paso` segundos."""
    salida = []
    t = 0.0
    while t + paso <= hasta:
        salida.append(
            Segmento(
                inicio=t,
                fin=t + paso - 0.5,
                texto=f"linea en {t:.0f}",
                palabras=[Palabra(texto="linea", inicio=t, fin=t + 0.4)],
            )
        )
        t += paso
    return salida


@pytest.fixture
def segmentos() -> list[Segmento]:
    return segmentos_cada(10.0, 3600.0)


def propuesto(inicio: float, fin: float, **extra: object) -> EpisodioPropuesto:
    duracion = fin - inicio
    base: dict[str, object] = {
        "inicio": inicio,
        "fin": fin,
        "titulo": f"ep {inicio:.0f}",
        "razon": "porque sí",
        "cumbre": inicio + duracion * 0.6,
        "desenlace": inicio + duracion * 0.8,
        "resumen": "pasa algo",
        "cliffhanger": "queda algo abierto",
        "puntuacion": 8,
    }
    base.update(extra)
    return EpisodioPropuesto(**base)  # type: ignore[arg-type]


# --- fronteras -------------------------------------------------------------


def test_ajustar_a_frontera_lleva_al_segmento_mas_cercano(segmentos: list[Segmento]) -> None:
    assert ajustar_a_frontera(101.0, segmentos, "inicio") == 100.0


def test_ajustar_a_frontera_no_mueve_si_no_hay_nada_cerca(segmentos: list[Segmento]) -> None:
    # El segmento más próximo está a más de la tolerancia de 2 s.
    assert ajustar_a_frontera(105.0, segmentos, "inicio") == 105.0


def test_parte_una_palabra_detecta_el_corte_a_media_habla() -> None:
    segmentos = [
        Segmento(
            inicio=10,
            fin=12,
            texto="hola",
            palabras=[Palabra(texto="hola", inicio=10.0, fin=11.0)],
        )
    ]
    assert parte_una_palabra(10.5, segmentos) is True
    assert parte_una_palabra(11.5, segmentos) is False


# --- alineación de cortes --------------------------------------------------


def test_alinear_corte_prefiere_el_cambio_de_plano(segmentos: list[Segmento]) -> None:
    tiempo, modo = alinear_corte(101.0, "inicio", segmentos, [102.5], fps=30)
    assert modo is Alineacion.ESCENA
    assert tiempo == 102.5


def test_alinear_corte_en_el_fin_retrocede_un_frame(segmentos: list[Segmento]) -> None:
    tiempo, modo = alinear_corte(200.0, "fin", segmentos, [201.0], fps=25)
    assert modo is Alineacion.ESCENA
    assert tiempo == pytest.approx(201.0 - 1 / 25)


def test_alinear_corte_descarta_el_plano_que_parte_una_palabra() -> None:
    segmentos = [
        Segmento(
            inicio=100,
            fin=110,
            texto="hola",
            palabras=[Palabra(texto="hola", inicio=102.0, fin=103.0)],
        )
    ]
    # El corte visual cae dentro de la palabra: se cae a frontera de frase.
    tiempo, modo = alinear_corte(101.0, "inicio", segmentos, [102.5], fps=30)
    assert modo is Alineacion.FRASE
    assert tiempo == 100.0


def test_alinear_corte_sin_nada_cerca_deja_lo_que_dijo_el_modelo() -> None:
    tiempo, modo = alinear_corte(500.0, "inicio", [], [], fps=30)
    assert modo is Alineacion.LLM
    assert tiempo == 500.0


# --- normalización de la serie ---------------------------------------------


def test_serie_correcta_pasa_sin_avisos(segmentos: list[Segmento]) -> None:
    resultado = normalizar_episodios(
        [propuesto(0, 270), propuesto(300, 570), propuesto(600, 870)],
        segmentos,
        3600.0,
    )
    assert len(resultado.episodios) == 3
    assert [e.parte for e in resultado.episodios] == [1, 2, 3]
    assert all(e.total_partes == 3 for e in resultado.episodios)
    assert not resultado.avisos


def test_solape_se_trunca_en_vez_de_descartar(segmentos: list[Segmento]) -> None:
    """Descartar rompería la cadena de recaps; se recorta el inicio del segundo."""
    resultado = normalizar_episodios(
        [propuesto(0, 300), propuesto(200, 500)], segmentos, 3600.0
    )
    assert len(resultado.episodios) == 2
    assert resultado.episodios[1].inicio == resultado.episodios[0].fin


def test_episodio_demasiado_largo_se_recorta_a_frontera(segmentos: list[Segmento]) -> None:
    resultado = normalizar_episodios(
        [propuesto(0, 900), propuesto(1000, 1270)], segmentos, 3600.0
    )
    assert resultado.episodios[0].duracion <= DURACION_MAX


def test_episodio_corto_se_estira_hasta_el_minimo(segmentos: list[Segmento]) -> None:
    resultado = normalizar_episodios(
        [propuesto(0, 60), propuesto(400, 670)], segmentos, 3600.0
    )
    assert resultado.episodios[0].duracion >= DURACION_MIN


def test_episodio_corto_sin_sitio_se_fusiona_con_el_anterior(segmentos: list[Segmento]) -> None:
    """No hay hueco para estirar: en vez de perderlo, se absorbe en el anterior.

    El techo para estirar es el inicio del episodio siguiente, así que aquí el corto solo
    tendría 45 s de margen y necesita 120.
    """
    resultado = normalizar_episodios(
        [
            propuesto(0, 200),
            propuesto(200, 240, cliffhanger="el de verdad"),
            propuesto(245, 515),
        ],
        segmentos,
        3600.0,
    )
    assert len(resultado.episodios) == 2
    assert any("fusionado" in aviso for aviso in resultado.avisos)
    # La fusión conserva el cierre en tensión del episodio absorbido.
    assert resultado.episodios[0].cliffhanger == "el de verdad"


def test_arco_fuera_de_rango_se_recoloca(segmentos: list[Segmento]) -> None:
    resultado = normalizar_episodios(
        [
            propuesto(0, 270, cumbre=5000, desenlace=6000),
            propuesto(300, 570),
        ],
        segmentos,
        3600.0,
    )
    arco = resultado.episodios[0].arco
    assert arco is not None
    assert 0 < arco.cumbre < arco.desenlace < resultado.episodios[0].duracion
    assert any("cae fuera del episodio" in aviso for aviso in resultado.avisos)
    # El episodio queda marcado: ese arco es geometría, no una lectura del material.
    assert resultado.episodios[0].arco_estimado is True
    assert resultado.episodios[1].arco_estimado is False


def test_hueco_anterior_se_calcula_desde_el_episodio_previo(segmentos: list[Segmento]) -> None:
    resultado = normalizar_episodios(
        [propuesto(0, 270), propuesto(500, 770)], segmentos, 3600.0
    )
    assert resultado.episodios[0].hueco_anterior == 0
    assert resultado.episodios[1].hueco_anterior == pytest.approx(
        resultado.episodios[1].inicio - resultado.episodios[0].fin
    )


def test_un_solo_episodio_no_es_una_serie(segmentos: list[Segmento]) -> None:
    with pytest.raises(SerieInvalida, match="al menos 2 episodios"):
        normalizar_episodios([propuesto(0, 270)], segmentos, 3600.0)


def test_cobertura_excesiva_es_error_duro(segmentos: list[Segmento]) -> None:
    """Límite de copyright: cubrir casi toda la película es el patrón que detecta Content ID."""
    propuestos = [propuesto(i * 300, i * 300 + 300) for i in range(4)]
    with pytest.raises(SerieInvalida, match="por encima del"):
        normalizar_episodios(propuestos, segmentos_cada(10.0, 1500.0), 1500.0)


def test_falta_de_cliffhanger_solo_avisa(segmentos: list[Segmento]) -> None:
    resultado = normalizar_episodios(
        [propuesto(0, 270, cliffhanger=""), propuesto(300, 570)], segmentos, 3600.0
    )
    assert len(resultado.episodios) == 2
    assert any("sin cliffhanger" in aviso for aviso in resultado.avisos)


def test_salto_muy_grande_avisa_para_que_el_recap_lo_cubra(segmentos: list[Segmento]) -> None:
    resultado = normalizar_episodios(
        [propuesto(0, 270), propuesto(1000, 1270)], segmentos, 3600.0
    )
    assert any("salto de" in aviso for aviso in resultado.avisos)


# --- cobertura y score -----------------------------------------------------


def test_calcular_cobertura(segmentos: list[Segmento]) -> None:
    resultado = normalizar_episodios(
        [propuesto(0, 270), propuesto(300, 570)], segmentos, 3600.0
    )
    esperado = sum(e.duracion for e in resultado.episodios) / 3600.0
    assert calcular_cobertura(resultado.episodios, 3600.0) == pytest.approx(esperado)
    assert resultado.cobertura <= COBERTURA_MAX


def test_calidad_de_cortes_premia_el_cambio_de_plano() -> None:
    escena = calidad_de_cortes(AlineacionFronteras(inicio=Alineacion.ESCENA, fin=Alineacion.ESCENA))
    frase = calidad_de_cortes(AlineacionFronteras(inicio=Alineacion.FRASE, fin=Alineacion.FRASE))
    llm = calidad_de_cortes(AlineacionFronteras(inicio=Alineacion.LLM, fin=Alineacion.LLM))
    assert escena > frase > llm


def test_score_total_es_media_ponderada() -> None:
    from viralfarm.contratos.serie import PESOS_SCORE, ScoreEpisodio

    assert sum(PESOS_SCORE.values()) == pytest.approx(1.0)
    assert ScoreEpisodio().total == pytest.approx(0.0)

    perfecto = ScoreEpisodio(
        densidad_eventos=1, fuerza_cierre=1, autonomia=1, calidad_cortes=1, juicio_llm=1
    )
    assert perfecto.total == pytest.approx(1.0)


def test_el_score_no_es_un_numero_opaco() -> None:
    """Cada componente se persiste por separado: es lo que hace auditable la decisión."""
    from viralfarm.contratos.serie import ScoreEpisodio

    score = ScoreEpisodio(fuerza_cierre=0.8, autonomia=0.5)
    volcado = score.model_dump()
    assert set(volcado) == {
        "densidad_eventos",
        "fuerza_cierre",
        "autonomia",
        "calidad_cortes",
        "juicio_llm",
    }
    # Los pesos son política, no dato del artefacto: no viajan en el JSON.
    assert "PESOS" not in volcado


# --- tope de episodios ---------------------------------------------------------


def test_el_tope_respeta_el_limite_de_cobertura() -> None:
    """El fallo que encontró la primera prueba real con LLM.

    El pipeline TypeScript derivaba el tope solo de la duración: en una película de 20 min
    pedía 5 episodios, que cubrirían el 112 % del fuente, y la validación de cobertura los
    rechazaba después. Pedir lo imposible y fallar más tarde es peor que pedir menos.
    """
    from viralfarm.dominio.episodios import DURACION_OBJETIVO, tope_episodios

    for duracion in (1204.0, 3600.0, 5400.0, 7200.0):
        tope = tope_episodios(duracion)
        cobertura_pedida = tope * DURACION_OBJETIVO / duracion
        assert cobertura_pedida <= COBERTURA_MAX, (
            f"{duracion:.0f}s: {tope} episodios cubrirían el {cobertura_pedida * 100:.0f} %"
        )


def test_el_tope_nunca_baja_de_dos() -> None:
    """Una serie de un episodio no es una serie; que falle el validador, no el tope."""
    from viralfarm.dominio.episodios import tope_episodios

    assert tope_episodios(60.0) == 2
    assert tope_episodios(0.0) == 2


def test_el_tope_tiene_techo_absoluto() -> None:
    from viralfarm.dominio.episodios import TOPE_EPISODIOS, tope_episodios

    assert tope_episodios(100_000.0) == TOPE_EPISODIOS


def test_el_tope_crece_con_la_duracion() -> None:
    from viralfarm.dominio.episodios import tope_episodios

    assert tope_episodios(1204.0) < tope_episodios(3600.0) < tope_episodios(7200.0)


# --- regresión del primer diagnóstico real -----------------------------------


def test_el_arco_estimado_reproduce_las_proporciones_del_episodio_real(
    segmentos: list[Segmento],
) -> None:
    """El episodio 2 de la primera serie real: arco 0,62 / 0,85 de la duración.

    Sus valores propuestos (cumbre 1072, desenlace 1109) caían fuera del episodio tras el
    truncado, así que el código los sustituyó. El desenlace resultante cayó dentro de 92 s
    sin una sola palabra: por eso el flag importa.
    """
    from viralfarm.dominio.episodios import ARCO_CUMBRE_ESTIMADA, ARCO_DESENLACE_ESTIMADO

    resultado = normalizar_episodios(
        [propuesto(0, 270), propuesto(344, 701, cumbre=1072, desenlace=1109)],
        segmentos,
        1204.0,
    )
    ep = resultado.episodios[1]
    assert ep.arco_estimado is True
    assert ep.arco is not None
    assert ep.arco.cumbre == pytest.approx(ep.duracion * ARCO_CUMBRE_ESTIMADA)
    assert ep.arco.desenlace == pytest.approx(ep.duracion * ARCO_DESENLACE_ESTIMADO)


def test_truncar_un_episodio_invalida_sus_metadatos(segmentos: list[Segmento]) -> None:
    """El caso exacto del episodio 2: pedido 345–1203, entregado 345–701.

    Su `resumen` hablaba de escenas que se cayeron y el caption anunciaba un final que no
    ocurre. Sobrevive el 42 % del rango: los textos no pueden heredarse.
    """
    resultado = normalizar_episodios(
        [propuesto(0, 340), propuesto(345, 1203, resumen="Zeus y el plan del furgón")],
        segmentos,
        1204.0,
    )
    truncado = resultado.episodios[1]
    assert truncado.duracion <= DURACION_MAX
    assert truncado.metadatos_obsoletos is True
    assert any("se quedó fuera" in aviso for aviso in resultado.avisos)


def test_un_ajuste_pequeno_no_invalida_los_metadatos(segmentos: list[Segmento]) -> None:
    """Mover el corte a la frontera de frase más cercana no cambia de qué va el episodio."""
    resultado = normalizar_episodios(
        [propuesto(0, 271), propuesto(300, 570)], segmentos, 3600.0
    )
    assert all(not e.metadatos_obsoletos for e in resultado.episodios)


def test_la_fusion_invalida_los_metadatos(segmentos: list[Segmento]) -> None:
    """Dos resúmenes concatenados no son el resumen del episodio fusionado."""
    resultado = normalizar_episodios(
        [propuesto(0, 200), propuesto(200, 240), propuesto(245, 515)],
        segmentos,
        3600.0,
    )
    assert resultado.episodios[0].metadatos_obsoletos is True
