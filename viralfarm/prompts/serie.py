"""Paso de selección: de la película a la serie de episodios.

El modelo propone; `dominio/episodios.py` verifica y repara. Este módulo solo aporta el texto
y el contrato de la respuesta.

Los campos de la respuesta usan camelCase porque ese es el formato que el modelo genera con
más naturalidad y el que consume el pipeline TypeScript mientras dure la migración. El
artefacto que se escribe a disco es otra cosa (`contratos/serie.py`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from viralfarm.dominio.episodios import (
    COBERTURA_MAX,
    COLA_MINIMA,
    DURACION_MAX,
    DURACION_MIN,
    DURACION_OBJETIVO,
)

SISTEMA = """Eres guionista de series verticales. Conviertes una película larga en una SERIE
de episodios que se publican en orden, uno por entrega, en TikTok.

El producto NO son "los mejores momentos": es una serie. Reglas del formato:

1. ORDEN CRONOLÓGICO ESTRICTO. El episodio 2 empieza después de donde terminó el 1. Nunca
   vuelves atrás, nunca reordenas, nunca repites material.
2. CADA EPISODIO ES UN RANGO CONTIGUO [inicio, fin] del material. Jamás saltas DENTRO de un
   episodio.
3. COBERTURA HÍBRIDA. ENTRE un episodio y el siguiente sí puede haber hueco: te saltas el
   material de relleno. Donde la acción es continua, encadenas sin hueco (el fin de uno es
   exactamente el inicio del siguiente). Decides según el material: ni fuerzas la cobertura
   total ni fabricas saltos artificiales. Nunca te saltas algo que haga incomprensible el
   episodio siguiente.
4. ARCO POR EPISODIO. Cada episodio tiene planteamiento, CUMBRE (máxima tensión) y DESENLACE
   que cierra lo que abrió. Puede contener varios sub-arcos, pero el espectador termina el
   episodio satisfecho, no estafado.
5. CIERRE EN TENSIÓN. Después del desenlace, en los últimos segundos, plantas una tensión NUEVA
   que NO resuelves: una aparición, una decisión pendiente, una revelación a medias. Esa
   tensión es lo primero que resuelve el episodio siguiente. Este es el motor de la serie.
6. CONTINUIDAD. El resumen de un episodio es la materia prima del recap del siguiente.
   Escríbelo pensando en alguien que no vio la entrega anterior.

Cortas siempre en frontera de frase de la transcripción, nunca a mitad de diálogo, y a ser
posible en un cambio de escena.

Evitas: créditos, logos de productora, y tramos largos sin acción ni diálogo (marcados como
«sin diálogo» en la transcripción) salvo que sean escena en sí: una persecución, un silencio
cargado, un montaje musical."""


class EpisodioPropuestoLlm(BaseModel):
    """Un episodio tal como lo propone el modelo, en segundos absolutos del fuente."""

    model_config = ConfigDict(populate_by_name=True)

    inicio: float = Field(description="Segundo absoluto de inicio en el video fuente")
    fin: float = Field(description="Segundo absoluto de fin en el video fuente")
    titulo: str = Field(description="Título del episodio, con gancho, SIN el número de parte")
    razon: str = Field(description="Por qué este tramo funciona como episodio autónomo")
    cumbre: float = Field(description="Segundo ABSOLUTO del pico de tensión")
    desenlace: float = Field(description="Segundo ABSOLUTO en que se cierra el arco abierto")
    resumen: str = Field(description="2-3 frases de lo que ocurre; base del recap siguiente")
    cliffhanger: str = Field(description="La tensión que queda abierta al final, en una frase")
    puntuacion: float = Field(description="0-10, cuánto engancha el episodio")


class RespuestaSerie(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    titulo_serie: str = Field(alias="tituloSerie", description="Título de la serie completa")
    sinopsis: str = Field(description="Sinopsis de la serie en 2-3 frases")
    episodios: list[EpisodioPropuestoLlm]


def construir_prompt(
    transcripcion_formateada: str,
    duracion_fuente: float,
    max_episodios: int,
    idioma_origen: str,
    idioma_salida: str,
) -> str:
    """Prompt de usuario. `transcripcion_formateada` viene de `dominio.timeline`."""
    minutos = duracion_fuente / 60
    return f"""Película de {duracion_fuente:.0f} segundos ({minutos:.0f} minutos), hablada en \
{idioma_origen}. Transcripción con timestamps absolutos del fuente; las líneas «sin diálogo»
marcan tramos sin habla:

{transcripcion_formateada}

Divide la película en una serie de episodios.

- Cada episodio dura entre {DURACION_MIN:.0f} y {DURACION_MAX:.0f} segundos \
(objetivo {DURACION_OBJETIVO:.0f}).
- Como máximo {max_episodios} episodios. Devuelve los que el material dé de sí: menos
  episodios buenos siempre es mejor que estirar la serie con relleno.
- Los episodios NO pueden cubrir más del {COBERTURA_MAX * 100:.0f} % de la película: deja
  fuera el material que no aporta.
- Orden cronológico estricto, sin solapes.
- Para cada episodio: inicio < cumbre < desenlace < fin, con al menos {COLA_MINIMA:.0f} \
segundos entre `desenlace` y `fin` — ahí va el cierre en tensión.
- `titulo` sin numerar: el número de parte lo añade el sistema.
- `cliffhanger` del ÚLTIMO episodio: no dejes nada abierto, es el cierre de la historia.

Escribe titulo, razon, resumen, cliffhanger, tituloSerie y sinopsis en {idioma_salida}."""
