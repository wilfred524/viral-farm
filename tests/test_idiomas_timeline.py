"""Catálogo de idiomas y construcción de la línea de tiempo multimodal."""

from __future__ import annotations

import pytest

from viralfarm.contratos.comunes import Palabra, Segmento
from viralfarm.contratos.timeline import TipoEvento
from viralfarm.contratos.transcripcion import Transcripcion
from viralfarm.contratos.vision import Observacion, Vision
from viralfarm.dominio.idiomas import (
    VOZ_FALLBACK,
    es_idioma_conocido,
    idiomas_soportados,
    normalizar_codigo,
    resolver_idioma,
)
from viralfarm.dominio.timeline import construir_timeline, formatear_para_prompt

# --- idiomas ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("en-US", "en"), ("EN", "en"), ("en_us", "en"), ("  es  ", "es"), (None, ""), ("", "")],
)
def test_normalizar_codigo(entrada: str | None, esperado: str) -> None:
    assert normalizar_codigo(entrada) == esperado


def test_idioma_conocido_trae_voz_afinada() -> None:
    idioma = resolver_idioma("es-MX")
    assert idioma.codigo == "es"
    assert idioma.voz == "es-MX-JorgeNeural"
    assert idioma.palabras_por_segundo > 0


def test_idioma_desconocido_cae_a_la_voz_multilingue() -> None:
    """Whisper reconoce muchos más idiomas de los que aquí se afinan: no es un error."""
    idioma = resolver_idioma("sw")
    assert idioma.voz == VOZ_FALLBACK
    assert idioma.palabras_por_segundo > 0
    assert not es_idioma_conocido("sw")


def test_todos_los_idiomas_del_catalogo_estan_completos() -> None:
    for codigo in idiomas_soportados():
        idioma = resolver_idioma(codigo)
        assert idioma.voz
        assert idioma.nombre
        assert idioma.palabras_por_segundo > 0
        assert idioma.serie.cta and idioma.serie.cta_final
        assert idioma.serie.parte(2, 8)


# --- timeline --------------------------------------------------------------


def transcripcion_con(*ventanas: tuple[float, float]) -> Transcripcion:
    return Transcripcion(
        idioma="en",
        modelo="small",
        duracion=ventanas[-1][1] if ventanas else 0,
        segmentos=[
            Segmento(
                inicio=i,
                fin=f,
                texto=f"linea {i:.0f}",
                palabras=[Palabra(texto="linea", inicio=i, fin=i + 0.3)],
            )
            for i, f in ventanas
        ],
    )


def test_el_dialogo_entra_en_orden() -> None:
    timeline = construir_timeline(transcripcion_con((0, 5), (6, 10)), 10)
    assert [e.tipo for e in timeline.eventos] == [TipoEvento.DIALOGO, TipoEvento.DIALOGO]


def test_los_silencios_largos_se_marcan() -> None:
    """Sin esto el modelo solo ve diálogo y es ciego a la mitad no hablada de una película."""
    timeline = construir_timeline(transcripcion_con((0, 5), (60, 65)), 65)
    silencios = [e for e in timeline.eventos if e.tipo is TipoEvento.SILENCIO]
    assert len(silencios) == 1
    assert silencios[0].inicio == 5
    assert silencios[0].fin == 60


def test_los_silencios_cortos_no_ensucian_la_linea() -> None:
    timeline = construir_timeline(transcripcion_con((0, 5), (10, 15)), 15)
    assert all(e.tipo is not TipoEvento.SILENCIO for e in timeline.eventos)


def test_la_cola_sin_dialogo_tambien_se_marca() -> None:
    timeline = construir_timeline(transcripcion_con((0, 5)), 100)
    assert timeline.eventos[-1].tipo is TipoEvento.SILENCIO
    assert timeline.eventos[-1].fin == 100


def test_sin_vision_la_linea_lo_declara() -> None:
    timeline = construir_timeline(transcripcion_con((0, 5)), 5)
    assert timeline.con_vision is False
    assert all(e.tipo is not TipoEvento.ACCION for e in timeline.eventos)


def test_con_vision_se_intercalan_las_acciones() -> None:
    vision = Vision(
        modelo="claude-sonnet-5",
        frames_analizados=2,
        observaciones=[
            Observacion(tiempo=3.0, accion="alguien entra por la puerta", intensidad=8),
        ],
    )
    timeline = construir_timeline(transcripcion_con((0, 5), (6, 10)), 10, vision=vision)
    assert timeline.con_vision is True
    acciones = [e for e in timeline.eventos if e.tipo is TipoEvento.ACCION]
    assert len(acciones) == 1
    assert acciones[0].intensidad == pytest.approx(0.8)
    # Y la secuencia sigue ordenada por tiempo.
    assert timeline.eventos == sorted(timeline.eventos, key=lambda e: e.inicio)


def test_el_prompt_distingue_los_tipos_de_evento() -> None:
    vision = Vision(
        modelo="m",
        frames_analizados=1,
        observaciones=[Observacion(tiempo=7.0, accion="se abre la puerta")],
    )
    timeline = construir_timeline(transcripcion_con((0, 5), (60, 65)), 65, vision=vision)
    texto = formatear_para_prompt(timeline)
    assert "«sin diálogo" in texto
    assert "▸ se abre la puerta" in texto
    assert "linea 0" in texto


# --- recorte a episodio: lo que el guionista debe ver -------------------------


def test_el_recorte_revela_un_silencio_que_la_pelicula_entera_escondia() -> None:
    """El caso del episodio 1 real: un hueco de 58 s que el guionista nunca vio.

    En la película entera ese hueco puede quedar por debajo del umbral o diluido entre
    otros; dentro de un episodio de 340 s es un sexto del metraje.
    """
    from viralfarm.dominio.timeline import recortar_a_episodio

    completa = construir_timeline(transcripcion_con((100, 105), (163, 168), (170, 175)), 400)
    trozo = recortar_a_episodio(completa, 100, 200)

    silencios = [e for e in trozo.eventos if e.tipo is TipoEvento.SILENCIO]
    assert len(silencios) >= 1
    grande = max(silencios, key=lambda e: e.duracion)
    assert grande.duracion == pytest.approx(58.0)
    assert "58 s" in grande.texto


def test_el_recorte_devuelve_tiempos_relativos_al_episodio() -> None:
    from viralfarm.dominio.timeline import recortar_a_episodio

    completa = construir_timeline(transcripcion_con((100, 105), (110, 115)), 400)
    trozo = recortar_a_episodio(completa, 100, 200)
    assert trozo.duracion == 100
    assert trozo.eventos[0].inicio == pytest.approx(0.0)


def test_el_recorte_marca_la_cola_muda_del_final() -> None:
    """El episodio 1 real terminaba con 19 s sin una palabra."""
    from viralfarm.dominio.timeline import recortar_a_episodio

    completa = construir_timeline(transcripcion_con((0, 5), (10, 20)), 100)
    trozo = recortar_a_episodio(completa, 0, 60)
    assert trozo.eventos[-1].tipo is TipoEvento.SILENCIO
    assert trozo.eventos[-1].fin == pytest.approx(60.0)


def test_el_recorte_deja_fuera_lo_que_no_pertenece_al_episodio() -> None:
    from viralfarm.dominio.timeline import recortar_a_episodio

    completa = construir_timeline(transcripcion_con((10, 15), (300, 305)), 400)
    trozo = recortar_a_episodio(completa, 0, 100)
    assert all("linea 300" not in e.texto for e in trozo.eventos)


# --- plantillas de prompt ----------------------------------------------------


def test_las_plantillas_cargan_y_tienen_version() -> None:
    """Los prompts viven en markdown; el hash permite atribuir una mejora a un cambio."""
    from viralfarm.prompts import guion, serie

    for v in (serie.version_sistema(), serie.version_usuario(),
              guion.version_sistema(), guion.version_usuario()):
        assert len(v) == 8 and v.isalnum()


def test_un_marcador_sin_valor_falla_al_cargar_no_a_mitad_de_una_serie() -> None:
    from viralfarm.prompts import plantillas

    with pytest.raises(plantillas.PlantillaInvalida, match="marcadores que nadie rellena"):
        plantillas.render("serie.usuario", duracion="1204")


def test_pasar_un_valor_que_la_plantilla_no_usa_tambien_falla() -> None:
    """Suele significar que alguien renombró un marcador en el markdown y olvidó un sitio."""
    from viralfarm.prompts import plantillas

    with pytest.raises(plantillas.PlantillaInvalida, match="no usa"):
        plantillas.render("serie.sistema", inventado="x")


def test_los_limites_numericos_salen_del_dominio_no_del_markdown() -> None:
    """El prompt no puede prometer un tope distinto del que el código va a exigir."""
    from viralfarm.dominio.episodios import DURACION_MAX, DURACION_MIN
    from viralfarm.prompts.serie import construir_prompt

    p = construir_prompt("[0.0] hola", 1204.0, 2, "inglés", "inglés")
    assert f"entre {DURACION_MIN:.0f} y {DURACION_MAX:.0f} segundos" in p


def test_el_arco_estimado_no_se_presenta_como_un_pico_real() -> None:
    """Regresión del episodio 2: su desenlace estimado caía en 92 s de silencio."""
    from viralfarm.prompts.guion import DatosGuion, sistema

    base = dict(
        idioma_salida="inglés", palabras_por_segundo=2.9, parte=2, total_partes=2,
        titulo_serie="X", duracion=357.5, desde=8.0, max_original=35,
        max_palabras_recap=22, cumbre=221.0, desenlace=303.0,
    )
    real = sistema(DatosGuion(**base, arco_estimado=False))
    estimado = sistema(DatosGuion(**base, arco_estimado=True))

    assert "Alrededor del segundo 221" in real
    assert "Alrededor del segundo 221" not in estimado
    assert "No hay una lectura fiable" in estimado
