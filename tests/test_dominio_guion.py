"""Ensamblado del guion: lo que el código garantiza pase lo que pase en la respuesta del LLM."""

from __future__ import annotations

from viralfarm.contratos.comunes import Procedencia
from viralfarm.contratos.serie import Arco, Episodio
from viralfarm.dominio.guion import ensamblar
from viralfarm.dominio.idiomas import resolver_idioma
from viralfarm.dominio.tramos import RECAP_SEG
from viralfarm.prompts.guion import RespuestaGuion, TramoLlm

INGLES = resolver_idioma("en")


def _episodio(parte: int, duracion: float = 300.0) -> Episodio:
    return Episodio(
        indice=parte - 1,
        inicio=0.0,
        fin=duracion,
        titulo="The Returned Check",
        razon="—",
        parte=parte,
        total_partes=3,
        arco=Arco(cumbre=180.0, desenlace=260.0),
    )


def _respuesta(**extra: object) -> RespuestaGuion:
    base: dict[str, object] = {
        "hook": "His cousin was never his cousin",
        "recap": "",
        "tramos": [
            TramoLlm(tipo="narracion", inicio=0.0, fin=20.0, texto="A stranger knocks"),
            TramoLlm(tipo="original", inicio=20.0, fin=300.0, texto=""),
        ],
        "resumen": "Vic descubre que el cheque rebotó.",
        "cliffhanger": "El desconocido vuelve.",
        "caption": "Watch what happens next",
        "hashtags": ["#thriller", "movie"],
    }
    base.update(extra)
    return RespuestaGuion.model_validate(base)


def test_los_tramos_cubren_el_episodio_entero_aunque_el_modelo_se_quede_corto() -> None:
    """Invariante del montaje: sin huecos ni solapes, y el último llega al final exacto."""
    respuesta = _respuesta(
        tramos=[TramoLlm(tipo="narracion", inicio=0.0, fin=12.0, texto="Algo pasa")]
    )

    guion = ensamblar(respuesta, _episodio(1), INGLES, 3).guion

    assert guion.tramos[0].inicio == 0.0
    assert guion.tramos[-1].fin == 300.0


def test_la_parte_2_abre_siempre_con_recap_aunque_el_modelo_lo_ignore() -> None:
    """Lo coloca el código: es lo que hace que quien llegue nuevo entienda el episodio."""
    respuesta = _respuesta(
        tramos=[TramoLlm(tipo="original", inicio=RECAP_SEG, fin=300.0, texto="")]
    )

    resultado = ensamblar(respuesta, _episodio(2), INGLES, 3)

    primero = resultado.guion.tramos[0]
    assert primero.inicio == 0.0 and primero.fin == RECAP_SEG
    assert primero.texto and resultado.guion.recap == primero.texto
    assert any("no devolvió recap" in a for a in resultado.avisos)


def test_la_parte_1_no_lleva_recap() -> None:
    guion = ensamblar(_respuesta(recap="ignórame"), _episodio(1), INGLES, 3).guion

    assert guion.recap == ""
    assert guion.tramos[0].inicio == 0.0


def test_un_tipo_de_tramo_desconocido_se_trata_como_audio_original() -> None:
    """Dejar sonar la película nunca rompe nada; inventar voz sobre un tramo mudo, sí."""
    respuesta = _respuesta(
        tramos=[
            TramoLlm(tipo="voiceover", inicio=0.0, fin=30.0, texto="texto que se descarta"),
            TramoLlm(tipo="original", inicio=30.0, fin=300.0, texto=""),
        ]
    )

    guion = ensamblar(respuesta, _episodio(1), INGLES, 3).guion

    assert guion.tramos_narrados() == []


def test_el_caption_lo_numera_el_codigo_no_el_modelo() -> None:
    guion = ensamblar(_respuesta(caption="Part 1/3 — Watch now"), _episodio(1), INGLES, 3).guion

    assert guion.caption.startswith("Part 1/3 —")
    assert guion.caption.count("Part 1/3") == 1
    assert guion.hashtags == ["thriller", "movie"]


def test_la_procedencia_viaja_al_artefacto() -> None:
    """Sin esto no se puede atribuir una mejora a un cambio de prompt."""
    procedencia = Procedencia(
        modelo="deepseek-chat", prompt_sistema="5e117770", prompt_usuario="a1"
    )

    guion = ensamblar(_respuesta(), _episodio(1), INGLES, 3, procedencia).guion

    assert guion.procedencia is not None
    assert guion.procedencia.etiqueta == "5e117770+a1"


def test_un_guion_sin_procedencia_sigue_siendo_valido() -> None:
    """Los artefactos anteriores al versionado se tienen que poder seguir leyendo."""
    guion = ensamblar(_respuesta(), _episodio(1), INGLES, 3).guion

    assert guion.procedencia is None
    assert guion.model_validate_json(guion.model_dump_json()).procedencia is None


def test_una_respuesta_sin_tramos_deja_el_episodio_intacto_y_se_queja() -> None:
    """Preferimos la película entera sin voz a un episodio roto — pero que conste el aviso."""
    resultado = ensamblar(_respuesta(tramos=[]), _episodio(1), INGLES, 3)

    assert len(resultado.guion.tramos) == 1
    assert resultado.guion.tramos_narrados() == []
    assert resultado.guion.duracion == 300.0
    assert resultado.avisos
