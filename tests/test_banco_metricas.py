"""El banco de pruebas mide lo que el diagnóstico encontró a mano.

Si estas cifras dejan de salir, lo primero sospechoso es la medición: los números vienen de
la primera serie real (2026-08-06, DeepSeek, `pelicula-prueba-05-25`), contados uno a uno
sobre los artefactos antes de que existiera este módulo.
"""

from __future__ import annotations

from viralfarm.banco.metricas import Medida, comparar, medir, tabla, voz_estimada
from viralfarm.contratos.guion import Guion, TipoTramo, Tramo
from viralfarm.contratos.voz import Voz, VozTramo

PPS = 2.9  # inglés


def _tramo(inicio: float, fin: float, texto: str = "") -> Tramo:
    tipo = TipoTramo.NARRACION if texto else TipoTramo.ORIGINAL
    return Tramo(tipo=tipo, inicio=inicio, fin=fin, texto=texto)


def _guion(tramos: list[Tramo], **extra: object) -> Guion:
    return Guion(indice=0, hook="A returned check", tramos=tramos, **extra)  # type: ignore[arg-type]


def test_un_tramo_narrado_con_poca_voz_se_contabiliza_como_aire_muerto() -> None:
    """El caso real: 16,4 s asignados con 4,1 s de voz dentro."""
    doce_palabras = " ".join(["word"] * 12)
    guion = _guion([_tramo(0, 16.4, doce_palabras), _tramo(16.4, 100.0)])

    m = medir(guion, PPS)

    assert m.densidad_declarada > 0.16  # el sistema cree que narra el 16 % del episodio
    assert m.densidad_voz < 0.05  # y suenan 4,1 s de 100
    assert 12.0 < m.aire_muerto < 13.0
    assert m.tramos_vacios == 1


def test_la_voz_medida_manda_sobre_la_estimada_cuando_existe() -> None:
    """Con `voz.json` la cifra deja de ser un proxy y la tabla deja de avisar."""
    guion = _guion([_tramo(0, 20.0, " ".join(["word"] * 40)), _tramo(20.0, 100.0)])
    voz = Voz(
        voz="en-US-AndrewNeural",
        tramos=[VozTramo(tramo=0, archivo="0.mp3", desplazamiento=0.0, duracion=5.0)],
    )

    m = medir(guion, PPS, voz)

    assert not m.estimada
    assert abs(m.densidad_voz - 0.05) < 1e-9
    assert abs(m.aire_muerto - 15.0) < 1e-9
    assert "estimados" not in tabla([m])


def test_las_fronteras_enteras_delatan_un_reparto_mecanico() -> None:
    """19 de 27 fronteras del episodio 2 eran enteros exactos: el modelo repartía duración."""
    redondo = _guion([_tramo(0, 8.0, "x"), _tramo(8.0, 16.0, "x"), _tramo(16.0, 24.0)])
    leido = _guion([_tramo(0, 7.84, "x"), _tramo(7.84, 15.31, "x"), _tramo(15.31, 23.62)])

    assert medir(redondo, PPS).fraccion_redondas == 1.0
    assert medir(leido, PPS).fraccion_redondas < 0.4


def test_el_metronomo_da_dispersion_casi_nula() -> None:
    """13 de 14 tramos entre 5,8 y 8,0 s. Un reparto vivo no se parece a eso."""
    metronomo = _guion(
        [_tramo(i * 7.0, (i + 1) * 7.0, "palabra palabra") for i in range(6)]
    )
    variado = _guion(
        [
            _tramo(0, 4.0, "x"),
            _tramo(4.0, 22.0, "x"),
            _tramo(22.0, 27.5, "x"),
            _tramo(27.5, 45.0, "x"),
        ]
    )

    assert medir(metronomo, PPS).dispersion_narrados < 0.01
    assert medir(variado, PPS).dispersion_narrados > 6.0


def test_la_voz_estimada_ignora_los_tramos_sin_texto() -> None:
    guion = _guion([_tramo(0, 10.0, "una dos tres"), _tramo(10.0, 30.0)])

    voz = voz_estimada(guion, PPS)

    assert [t.tramo for t in voz.tramos] == [0]
    assert abs(voz.tramos[0].duracion - 3 / PPS) < 1e-9


def test_la_comparacion_dice_si_una_version_mejora_o_empeora() -> None:
    """La tabla no es decorativa: nombra la dirección del cambio para no interpretarla mal."""
    peor = [medir(_guion([_tramo(0, 20.0, "una dos"), _tramo(20.0, 100.0)]), PPS)]
    mejor = [medir(_guion([_tramo(0, 20.0, " ".join(["x"] * 55)), _tramo(20.0, 100.0)]), PPS)]

    texto = comparar(peor, mejor, ("antes", "despues"))

    assert "densidad de voz" in texto
    assert "mejor" in texto
    assert "aire muerto por episodio" in texto


def test_la_tabla_vacia_no_revienta() -> None:
    assert tabla([]) == "(sin episodios que medir)"


def test_la_brecha_es_la_distancia_entre_lo_que_el_sistema_cree_y_lo_que_suena() -> None:
    m: Medida = medir(_guion([_tramo(0, 40.0, "una dos"), _tramo(40.0, 100.0)]), PPS)

    assert abs(m.brecha_densidad - (m.densidad_declarada - m.densidad_voz)) < 1e-9
    assert m.brecha_densidad > 0.3
