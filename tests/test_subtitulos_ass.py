"""Subtítulos y su serialización a ASS — lo que sustituye al render de Remotion."""

from __future__ import annotations

import pytest

from viralfarm.contratos.comunes import Palabra, Segmento
from viralfarm.contratos.guion import Guion, TipoTramo, Tramo
from viralfarm.contratos.subtitulos import OrigenSubtitulo, Subtitulo
from viralfarm.contratos.voz import Voz, VozTramo
from viralfarm.dominio.ass import DURACION_HOOK, EstiloAss, generar_ass
from viralfarm.dominio.ducking import db_a_factor, expresion_ducking
from viralfarm.dominio.subtitulos import agrupar_en_lineas, construir_subtitulos


@pytest.fixture
def guion() -> Guion:
    return Guion(
        indice=0,
        idioma="es",
        hook="Nadie vio esto venir",
        tramos=[
            Tramo(tipo=TipoTramo.NARRACION, inicio=0, fin=8, texto="recap de la anterior"),
            Tramo(tipo=TipoTramo.ORIGINAL, inicio=8, fin=20),
            Tramo(tipo=TipoTramo.NARRACION, inicio=20, fin=30, texto="y entonces"),
        ],
        caption="algo",
        parte=2,
        total_partes=5,
    )


@pytest.fixture
def segmentos() -> list[Segmento]:
    """Transcripción del fuente: el episodio empieza en el segundo 100."""
    return [
        Segmento(
            inicio=105,
            fin=115,
            texto="hola mundo",
            palabras=[
                Palabra(texto="hola", inicio=110.0, fin=110.5),
                Palabra(texto="mundo", inicio=111.0, fin=111.5),
            ],
        ),
        # Fuera del episodio: no debe aparecer.
        Segmento(
            inicio=500,
            fin=505,
            texto="lejos",
            palabras=[Palabra(texto="lejos", inicio=500.0, fin=500.5)],
        ),
    ]


@pytest.fixture
def voz() -> Voz:
    return Voz(
        voz="es-MX-JorgeNeural",
        tramos=[
            VozTramo(
                tramo=0,
                archivo="voz/0.mp3",
                desplazamiento=0.0,
                duracion=6.0,
                palabras=[
                    Palabra(texto="recap", inicio=0.0, fin=0.6),
                    Palabra(texto="anterior", inicio=0.7, fin=1.4),
                ],
            ),
            VozTramo(
                tramo=2,
                archivo="voz/2.mp3",
                desplazamiento=20.0,
                duracion=3.0,
                palabras=[Palabra(texto="entonces", inicio=0.0, fin=0.8)],
            ),
        ],
    )


# --- construcción ----------------------------------------------------------


def test_mezcla_palabras_del_original_y_de_la_voz(
    guion: Guion, segmentos: list[Segmento], voz: Voz
) -> None:
    subtitulos = construir_subtitulos(guion, segmentos, voz, inicio_episodio=100.0)
    origenes = {s.origen for s in subtitulos}
    assert origenes == {OrigenSubtitulo.ORIGINAL, OrigenSubtitulo.NARRACION}


def test_los_tiempos_son_relativos_al_episodio(
    guion: Guion, segmentos: list[Segmento], voz: Voz
) -> None:
    subtitulos = construir_subtitulos(guion, segmentos, voz, inicio_episodio=100.0)
    hola = next(s for s in subtitulos if s.texto == "hola")
    assert hola.inicio == pytest.approx(10.0)  # 110 absoluto − 100 de inicio


def test_descarta_lo_que_cae_fuera_del_episodio(
    guion: Guion, segmentos: list[Segmento], voz: Voz
) -> None:
    subtitulos = construir_subtitulos(guion, segmentos, voz, inicio_episodio=100.0)
    assert all(s.texto != "lejos" for s in subtitulos)


def test_la_voz_se_situa_en_su_desplazamiento(
    guion: Guion, segmentos: list[Segmento], voz: Voz
) -> None:
    subtitulos = construir_subtitulos(guion, segmentos, voz, inicio_episodio=100.0)
    entonces = next(s for s in subtitulos if s.texto == "entonces")
    assert entonces.inicio == pytest.approx(20.0)


def test_sin_voz_solo_quedan_las_palabras_del_original(
    guion: Guion, segmentos: list[Segmento]
) -> None:
    subtitulos = construir_subtitulos(guion, segmentos, None, inicio_episodio=100.0)
    assert subtitulos
    assert all(s.origen is OrigenSubtitulo.ORIGINAL for s in subtitulos)


def test_salen_ordenados(guion: Guion, segmentos: list[Segmento], voz: Voz) -> None:
    subtitulos = construir_subtitulos(guion, segmentos, voz, inicio_episodio=100.0)
    assert subtitulos == sorted(subtitulos, key=lambda s: s.inicio)


# --- agrupación ------------------------------------------------------------


def test_agrupar_no_mezcla_origenes_en_una_linea() -> None:
    subtitulos = [
        Subtitulo(texto="a", inicio=0, fin=1, origen=OrigenSubtitulo.NARRACION),
        Subtitulo(texto="b", inicio=1, fin=2, origen=OrigenSubtitulo.NARRACION),
        Subtitulo(texto="c", inicio=2, fin=3, origen=OrigenSubtitulo.ORIGINAL),
    ]
    lineas = agrupar_en_lineas(subtitulos)
    assert len(lineas) == 2
    assert [s.texto for s in lineas[0]] == ["a", "b"]


def test_agrupar_respeta_el_maximo_por_linea() -> None:
    subtitulos = [
        Subtitulo(texto=str(i), inicio=i, fin=i + 1, origen=OrigenSubtitulo.ORIGINAL)
        for i in range(9)
    ]
    lineas = agrupar_en_lineas(subtitulos, por_linea=4)
    assert [len(linea) for linea in lineas] == [4, 4, 1]


# --- ASS -------------------------------------------------------------------


def test_ass_tiene_cabecera_y_resolucion_vertical() -> None:
    ass = generar_ass("hook", [], ancho=1080, alto=1920)
    assert "[Script Info]" in ass
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass


def test_ass_pinta_el_hook_y_la_chapa_de_parte() -> None:
    ass = generar_ass("Nadie vio esto", [], parte=3, total_partes=8)
    assert "Nadie vio esto" in ass
    assert "3 / 8" in ass
    assert ",Hook,," in ass
    assert ",Chapa,," in ass


def test_ass_sin_parte_no_pinta_chapa() -> None:
    ass = generar_ass("solo hook", [])
    assert ",Chapa,," not in ass


def test_el_hook_dura_lo_declarado() -> None:
    ass = generar_ass("hook", [])
    linea = next(x for x in ass.splitlines() if x.startswith("Dialogue") and ",Hook," in x)
    # Formato: Dialogue: capa,inicio,fin,estilo,...
    fin = linea.split(",")[2]
    assert fin == "0:00:02.50"
    assert DURACION_HOOK == 2.5


def test_karaoke_emite_un_evento_por_palabra() -> None:
    subtitulos = [
        Subtitulo(texto="una", inicio=0.0, fin=0.5, origen=OrigenSubtitulo.NARRACION),
        Subtitulo(texto="dos", inicio=0.6, fin=1.0, origen=OrigenSubtitulo.NARRACION),
    ]
    ass = generar_ass("", subtitulos)
    eventos = [x for x in ass.splitlines() if x.startswith("Dialogue") and ",Subtitulo," in x]
    assert len(eventos) == 2
    # Cada evento contiene la línea completa; cambia cuál va resaltada.
    assert all("una" in e and "dos" in e for e in eventos)


def test_la_palabra_activa_se_resalta_en_color_distinto() -> None:
    estilo = EstiloAss()
    subtitulos = [
        Subtitulo(texto="hola", inicio=0.0, fin=1.0, origen=OrigenSubtitulo.NARRACION),
    ]
    ass = generar_ass("", subtitulos, estilo=estilo)
    # El color se escribe en BGR invertido: FFE45E → 5EE4FF
    assert "&H005EE4FF&" in ass


def test_original_y_narracion_usan_colores_distintos() -> None:
    narrado = generar_ass(
        "", [Subtitulo(texto="a", inicio=0, fin=1, origen=OrigenSubtitulo.NARRACION)]
    )
    original = generar_ass(
        "", [Subtitulo(texto="a", inicio=0, fin=1, origen=OrigenSubtitulo.ORIGINAL)]
    )
    assert narrado != original


def test_la_palabra_permanece_hasta_que_entra_la_siguiente() -> None:
    """Sin esto la línea parpadearía en los huecos entre palabras."""
    subtitulos = [
        Subtitulo(texto="una", inicio=0.0, fin=0.5, origen=OrigenSubtitulo.ORIGINAL),
        Subtitulo(texto="dos", inicio=2.0, fin=2.5, origen=OrigenSubtitulo.ORIGINAL),
    ]
    ass = generar_ass("", subtitulos)
    primero = next(x for x in ass.splitlines() if x.startswith("Dialogue") and ",Subtitulo," in x)
    assert primero.split(",")[2] == "0:00:02.00"


def test_escapa_las_llaves_que_ass_interpreta_como_marcado() -> None:
    ass = generar_ass("un {hook} raro", [])
    assert "\\{hook\\}" in ass


def test_tiempos_en_formato_ass() -> None:
    subtitulos = [
        Subtitulo(texto="x", inicio=3661.5, fin=3662.0, origen=OrigenSubtitulo.ORIGINAL)
    ]
    ass = generar_ass("", subtitulos)
    assert "1:01:01.50" in ass


def test_color_invalido_es_error() -> None:
    with pytest.raises(ValueError, match="color no válido"):
        generar_ass("x", [], estilo=EstiloAss(color_texto="ZZZ"))


# --- ducking ---------------------------------------------------------------


def test_sin_tramos_narrados_el_volumen_es_plano() -> None:
    assert expresion_ducking([], db_a_factor(-18)) == "1"


def test_db_a_factor() -> None:
    assert db_a_factor(0) == pytest.approx(1.0)
    assert db_a_factor(-6) == pytest.approx(0.501, abs=1e-3)
    assert db_a_factor(-18) == pytest.approx(0.1259, abs=1e-4)


def test_la_expresion_de_ducking_referencia_los_tramos() -> None:
    expresion = expresion_ducking([(10.0, 20.0)], db_a_factor(-18))
    assert expresion.startswith("1-0.8741*(")
    assert "9.750" in expresion  # inicio − rampa
    assert "20.250" in expresion  # fin + rampa


def test_varios_tramos_se_combinan_con_max() -> None:
    expresion = expresion_ducking([(0.0, 5.0), (10.0, 15.0)], db_a_factor(-18))
    assert expresion.count("max(") >= 2


def test_rampa_no_positiva_es_error() -> None:
    with pytest.raises(ValueError, match="rampa"):
        expresion_ducking([(0.0, 1.0)], 0.5, rampa=0)


def test_el_hook_largo_se_ajusta_en_varias_lineas() -> None:
    """Regresión del primer render real: el hook se salía del encuadre.

    `WrapStyle: 2` desactiva el ajuste automático. Vale para los subtítulos, cuyo corte
    decide `agrupar_en_lineas`, pero el hook es una frase libre que el modelo escribe sin
    límite: sin ajuste, una frase larga se sale por los dos lados de un 1080 de ancho.
    """
    ass = generar_ass("A returned check exposes a dark family secret.", [])
    assert "WrapStyle: 0" in ass, "el hook necesita ajuste automático de línea"
    assert "WrapStyle: 2" not in ass


def test_los_margenes_dejan_ancho_util_al_hook() -> None:
    """Con el ajuste activo, el ancho útil lo fijan los márgenes laterales."""
    estilo = EstiloAss()
    ancho_util = 1080 - 2 * estilo.margen_lateral
    assert ancho_util >= 900, "menos de 900 px deja el hook demasiado estrecho"
