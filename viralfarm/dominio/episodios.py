"""Normalización y reparación de la serie de episodios.

En ambos formatos el LLM **propone** y el código **verifica**. La diferencia está en qué se
hace con lo que no cuadra: en `virales` se descarta; en `serie` se REPARA — descartar un
episodio rompe la cadena de recaps y cliffhangers de todos los que vienen detrás.

Módulo puro: no lee disco ni llama a nadie. Los avisos se devuelven en el resultado en vez de
imprimirse, que es lo que permite testear el comportamiento de reparación.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from viralfarm.contratos.comunes import Segmento
from viralfarm.contratos.serie import (
    Alineacion,
    AlineacionFronteras,
    Arco,
    Episodio,
    ScoreEpisodio,
)

# --- formato serie ---
DURACION_MIN = 120.0
DURACION_OBJETIVO = 270.0
DURACION_MAX = 360.0
#: Segundos entre el desenlace y el final del episodio: ahí va el cierre en tensión.
COLA_MINIMA = 10.0
#: Hueco sin habla que se marca en el prompt para que el modelo no sea ciego a lo no dialogado.
SILENCIO_NOTABLE = 15.0
#: Tope de fracción del fuente que pueden cubrir los episodios.
#:
#: Trozos contiguos y en orden que cubren casi toda la película es justo el patrón que detectan
#: los sistemas de copyright, y debilita el argumento de uso transformativo. Ver `riesgos.md`.
COBERTURA_MAX = 0.6
#: Salto desde el episodio anterior a partir del cual se avisa: el recap tendrá que cubrirlo.
HUECO_NOTABLE = 300.0

# --- formato virales (legado) ---
VIRAL_MIN = 20.0
VIRAL_MAX = 60.0

#: Tolerancia al buscar frontera de frase, en segundos.
TOLERANCIA_FRONTERA = 2.0

#: Fracción del rango propuesto que debe sobrevivir a la reparación para que el `resumen` y
#: el `cliffhanger` del modelo sigan describiendo el episodio. Por debajo, los textos hablan
#: de material que se quedó fuera y hay que regenerarlos.
#:
#: No es un número redondo por gusto: en la primera serie real el episodio 2 se pidió como
#: 345–1203 s y quedó en 345–701, o sea el 42 % de lo propuesto. Su resumen siguió
#: describiendo escenas ausentes y el caption anunciaba un final que nunca ocurre.
FRACCION_METADATOS_VALIDOS = 0.9


class SerieInvalida(ValueError):
    """La serie no cumple una invariante dura. Se prefiere fallar antes que renderizar horas."""


@dataclass
class EpisodioPropuesto:
    """Lo que devuelve el modelo, antes de que el código lo verifique."""

    inicio: float
    fin: float
    titulo: str
    razon: str
    cumbre: float
    desenlace: float
    resumen: str = ""
    cliffhanger: str = ""
    puntuacion: float = 0.0
    alineacion: AlineacionFronteras = field(default_factory=AlineacionFronteras)
    #: Lo marca la reparación cuando mueve las fronteras: `resumen` y `cliffhanger` fueron
    #: escritos para otro rango y ya no describen lo que hay dentro.
    metadatos_obsoletos: bool = False


@dataclass
class ResultadoSerie:
    episodios: list[Episodio]
    cobertura: float
    #: Problemas no bloqueantes. Quien orquesta decide si los imprime o los registra.
    avisos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fronteras y cortes
# ---------------------------------------------------------------------------


def fronteras(segmentos: Sequence[Segmento], extremo: str) -> list[float]:
    """Instantes de inicio o de fin de segmento, ordenados."""
    if extremo not in ("inicio", "fin"):
        raise ValueError(f"extremo debe ser 'inicio' o 'fin', no {extremo!r}")
    return sorted(getattr(s, extremo) for s in segmentos)


def ajustar_a_frontera(
    tiempo: float,
    segmentos: Sequence[Segmento],
    extremo: str,
    tolerancia: float = TOLERANCIA_FRONTERA,
) -> float:
    """Lleva un instante al comienzo/fin de segmento más cercano para no cortar frases.

    Si no hay ninguno dentro de la tolerancia, devuelve el instante sin tocar.
    """
    mejor = tiempo
    distancia = float("inf")
    for candidato in (getattr(s, extremo) for s in segmentos):
        d = abs(candidato - tiempo)
        if d < distancia and d <= tolerancia:
            distancia = d
            mejor = candidato
    return mejor


def parte_una_palabra(tiempo: float, segmentos: Sequence[Segmento]) -> bool:
    """True si el instante cae DENTRO de una palabra: cortar ahí parte el habla por la mitad."""
    for segmento in segmentos:
        if segmento.fin < tiempo or segmento.inicio > tiempo:
            continue
        for palabra in segmento.palabras:
            if palabra.inicio < tiempo < palabra.fin:
                return True
    return False


def alinear_corte(
    tiempo: float,
    extremo: str,
    segmentos: Sequence[Segmento],
    cortes_visuales: Sequence[float],
    fps: float,
) -> tuple[float, Alineacion]:
    """Alinea una frontera a un cambio de plano, con reserva a frontera de frase.

    Un corte visual que parte una palabra por la mitad es peor que no alinear, así que esos se
    descartan. `cortes_visuales` viene ordenado por cercanía al instante pedido.
    """
    for corte in cortes_visuales:
        # En el fin se retrocede un frame: dejar el primer frame del plano siguiente pegado al
        # final del episodio se lee como un fallo de edición.
        candidato = corte if extremo == "inicio" else max(0.0, corte - 1.0 / fps)
        if parte_una_palabra(candidato, segmentos):
            continue
        return candidato, Alineacion.ESCENA

    por_frase = ajustar_a_frontera(tiempo, segmentos, extremo)
    if por_frase != tiempo:
        return por_frase, Alineacion.FRASE
    return tiempo, Alineacion.LLM


# ---------------------------------------------------------------------------
# Reparación de la serie
# ---------------------------------------------------------------------------


def _reparar_duraciones(
    propuestos: Sequence[EpisodioPropuesto],
    finales: Sequence[float],
    duracion_fuente: float,
    avisos: list[str],
) -> list[EpisodioPropuesto]:
    """Trunca solapes, ajusta duraciones y fusiona lo que no llega al mínimo.

    Política: reparar antes que descartar. Solo se descarta un episodio corto cuando no hay con
    quién fusionarlo.
    """
    ordenados = sorted((e for e in propuestos if e.fin > e.inicio), key=lambda e: e.inicio)
    reparados: list[EpisodioPropuesto] = []

    for posicion, episodio in enumerate(ordenados):
        previo = reparados[-1] if reparados else None
        # Techo para estirar: donde empieza el siguiente propuesto, o el final del fuente.
        techo = ordenados[posicion + 1].inicio if posicion + 1 < len(ordenados) else duracion_fuente

        # 1. Solape: se trunca el inicio contra el episodio anterior, nunca se elimina.
        inicio = max(0.0, episodio.inicio)
        if previo is not None and inicio < previo.fin:
            inicio = previo.fin

        fin = min(duracion_fuente, episodio.fin)

        # 2. Duración: recortar por arriba y estirar por abajo, siempre a frontera de frase.
        if fin - inicio > DURACION_MAX:
            tope = inicio + DURACION_MAX
            candidatos = [f for f in finales if inicio < f <= tope]
            fin = candidatos[-1] if candidatos else tope

        if fin - inicio < DURACION_MIN:
            minimo = inicio + DURACION_MIN
            limite = min(duracion_fuente, techo)
            candidato = next((f for f in finales if minimo <= f <= limite), None)
            estirado = candidato if candidato is not None else (minimo if minimo <= limite else fin)
            if estirado - inicio <= DURACION_MAX:
                fin = estirado

        # 3. Si sigue sin caber, fusionar con el anterior antes de rendirse.
        if fin - inicio < DURACION_MIN:
            if previo is not None and fin - previo.inicio <= DURACION_MAX:
                avisos.append(
                    f'episodio "{episodio.titulo}" ({fin - inicio:.0f} s) '
                "fusionado con el anterior."
                )
                previo.fin = fin
                previo.cliffhanger = episodio.cliffhanger
                previo.resumen = f"{previo.resumen} {episodio.resumen}".strip()
                previo.desenlace = episodio.desenlace
                previo.cumbre = max(previo.cumbre, episodio.cumbre)
                previo.alineacion = AlineacionFronteras(
                    inicio=previo.alineacion.inicio, fin=episodio.alineacion.fin
                )
                # Dos resúmenes concatenados no son el resumen del episodio fusionado.
                previo.metadatos_obsoletos = True
                continue
            avisos.append(
                f'episodio "{episodio.titulo}" descartado: {fin - inicio:.0f} s, no llega al '
                f"mínimo de {DURACION_MIN:.0f} s y no hay con quién fusionarlo."
            )
            continue

        # Si la reparación se comió una parte apreciable del rango, `resumen` y
        # `cliffhanger` describen material que ya no está dentro.
        propuesto = episodio.fin - episodio.inicio
        superviviente = (fin - inicio) / propuesto if propuesto > 0 else 1.0
        obsoletos = superviviente < FRACCION_METADATOS_VALIDOS
        if obsoletos:
            avisos.append(
                f'episodio "{episodio.titulo}": la reparación conserva el '
                f"{superviviente * 100:.0f} % del rango propuesto, así que su resumen y su "
                "cierre describen material que se quedó fuera. Hay que regenerarlos."
            )

        reparados.append(
            replace(episodio, inicio=inicio, fin=fin, metadatos_obsoletos=obsoletos)
        )

    return reparados


#: Proporciones de reserva cuando el arco propuesto no cabe en el episodio. Son geometría,
#: no lectura del material: por eso el episodio queda marcado con `arco_estimado`.
ARCO_CUMBRE_ESTIMADA = 0.62
ARCO_DESENLACE_ESTIMADO = 0.85


def _arco_relativo(
    propuesto: EpisodioPropuesto, duracion: float, parte: int, avisos: list[str]
) -> tuple[Arco, bool]:
    """Arco a tiempos relativos. Devuelve `(arco, estimado)`.

    `estimado=True` significa que el modelo lo situó fuera del episodio y el código lo
    sustituyó por una proporción fija. Esa distinción no es cosmética: el arco viaja al
    prompt del guion como «aquí está el pico de tensión», y afirmarlo sobre un número
    inventado hace que el guionista proteja un momento que puede caer en mitad de un
    silencio — ocurrió en la primera serie real.
    """
    cumbre = propuesto.cumbre - propuesto.inicio
    desenlace = propuesto.desenlace - propuesto.inicio
    tope_desenlace = duracion - COLA_MINIMA

    if 0 < cumbre < desenlace <= tope_desenlace:
        return Arco(cumbre=cumbre, desenlace=desenlace), False

    cumbre = duracion * ARCO_CUMBRE_ESTIMADA
    desenlace = duracion * ARCO_DESENLACE_ESTIMADO
    avisos.append(
        f"episodio {parte}: el arco propuesto cae fuera del episodio; se estima en "
        f"cumbre {cumbre:.0f} s / desenlace {desenlace:.0f} s. Es geometría, no una "
        "lectura del material: el guion no debe tratarlo como un pico real."
    )
    return Arco(cumbre=cumbre, desenlace=desenlace), True


def _validar_invariantes(
    episodios: Sequence[Episodio], duracion_fuente: float, avisos: list[str]
) -> None:
    """Invariantes duras. Un error aquí se propaga a horas de render, así que se corta antes."""
    if len(episodios) < 2:
        raise SerieInvalida(
            f"Una serie necesita al menos 2 episodios y solo sobrevivió {len(episodios)}. "
            "Revisa la transcripción o usa el formato `virales`."
        )

    for i, e in enumerate(episodios):
        if not (DURACION_MIN <= e.duracion <= DURACION_MAX):
            raise SerieInvalida(
                f"Episodio {e.parte} dura {e.duracion:.0f} s, "
                f"fuera de [{DURACION_MIN:.0f}, {DURACION_MAX:.0f}]."
            )
        if e.inicio < 0 or e.fin > duracion_fuente:
            raise SerieInvalida(f"Episodio {e.parte} se sale del fuente ({e.inicio}–{e.fin}).")
        if i > 0 and e.inicio < episodios[i - 1].fin:
            raise SerieInvalida(f"Episodio {e.parte} solapa con el anterior.")
        if e.parte != i + 1 or e.total_partes != len(episodios):
            raise SerieInvalida(f"Numeración incorrecta en el episodio {i + 1}.")

        if i < len(episodios) - 1 and not (e.cliffhanger or "").strip():
            avisos.append(f"episodio {e.parte} sin cliffhanger: la serie pierde tirón ahí.")
        if e.hueco_anterior > HUECO_NOTABLE:
            avisos.append(
                f"episodio {e.parte}: salto de {e.hueco_anterior / 60:.1f} min desde el "
                "anterior; el recap tendrá que cubrirlo."
            )


def normalizar_episodios(
    propuestos: Sequence[EpisodioPropuesto],
    segmentos: Sequence[Segmento],
    duracion_fuente: float,
) -> ResultadoSerie:
    """Fuerza las invariantes de la serie sobre lo que propuso el modelo.

    Orden, contigüidad, duración, arco, numeración y cobertura. Lanza `SerieInvalida` si algo
    no tiene arreglo; devuelve los avisos de lo que sí se pudo reparar.
    """
    avisos: list[str] = []
    reparados = _reparar_duraciones(
        propuestos, fronteras(segmentos, "fin"), duracion_fuente, avisos
    )

    episodios: list[Episodio] = []
    for posicion, propuesto in enumerate(reparados):
        anterior = reparados[posicion - 1] if posicion > 0 else None
        arco, arco_estimado = _arco_relativo(
            propuesto, propuesto.fin - propuesto.inicio, posicion + 1, avisos
        )
        episodios.append(
            Episodio(
                indice=posicion,
                inicio=propuesto.inicio,
                fin=propuesto.fin,
                titulo=propuesto.titulo,
                razon=propuesto.razon,
                parte=posicion + 1,
                total_partes=len(reparados),
                arco=arco,
                arco_estimado=arco_estimado,
                metadatos_obsoletos=propuesto.metadatos_obsoletos,
                resumen=propuesto.resumen,
                cliffhanger=propuesto.cliffhanger,
                hueco_anterior=max(0.0, propuesto.inicio - anterior.fin) if anterior else 0.0,
                alineacion=propuesto.alineacion,
                score=ScoreEpisodio(
                    juicio_llm=max(0.0, min(10.0, propuesto.puntuacion)) / 10.0,
                    calidad_cortes=calidad_de_cortes(propuesto.alineacion),
                ),
            )
        )

    _validar_invariantes(episodios, duracion_fuente, avisos)

    cobertura = calcular_cobertura(episodios, duracion_fuente)
    if cobertura > COBERTURA_MAX:
        raise SerieInvalida(
            f"Los episodios cubren el {cobertura * 100:.0f} % de la película, por encima del "
            f"{COBERTURA_MAX * 100:.0f} % permitido. Reduce el número de episodios o deja más "
            "huecos entre ellos (ver docs/riesgos.md)."
        )

    return ResultadoSerie(episodios=episodios, cobertura=cobertura, avisos=avisos)


#: Tope absoluto de episodios en una serie, independientemente de la duración.
TOPE_EPISODIOS = 40


def tope_episodios(duracion_fuente: float, cobertura_max: float = COBERTURA_MAX) -> int:
    """Cuántos episodios se le pueden pedir al modelo como máximo.

    El tope sale del **límite de cobertura**, no solo de la duración: pedir más episodios de
    los que caben bajo `COBERTURA_MAX` garantiza que la serie se rechace después. El pipeline
    TypeScript derivaba el tope solo de la duración (`ceil(duracion / 270)`), así que en una
    película de 20 minutos pedía 5 episodios —el 112 % del fuente— y la validación de
    cobertura los tumbaba sin remedio.

    Devuelve al menos 2, porque una serie de un episodio no es una serie: si el material no da
    para dos, `normalizar_episodios` lo dirá con un error claro en vez de callar aquí.
    """
    if duracion_fuente <= 0:
        return 2
    cabe = int(duracion_fuente * cobertura_max // DURACION_OBJETIVO)
    return max(2, min(TOPE_EPISODIOS, cabe))


def calcular_cobertura(episodios: Sequence[Episodio], duracion_fuente: float) -> float:
    """Fracción del fuente cubierta por los episodios. Control de calidad y de riesgo legal."""
    if duracion_fuente <= 0:
        return 0.0
    return sum(e.duracion for e in episodios) / duracion_fuente


def calidad_de_cortes(alineacion: AlineacionFronteras) -> float:
    """Componente del score: cortar en cambio de plano > en frase > donde dijo el modelo."""
    valor = {Alineacion.ESCENA: 1.0, Alineacion.FRASE: 0.6, Alineacion.LLM: 0.2}
    return (valor[alineacion.inicio] + valor[alineacion.fin]) / 2
