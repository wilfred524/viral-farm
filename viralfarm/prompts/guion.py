"""Paso de guion: hook, reparto en tramos, caption y hashtags de un episodio.

En formato serie hay continuidad: cada episodio abre con un recap narrado de la entrega
anterior y cierra verbalizando la tensión que queda abierta. Ese recap **no** se deja a
criterio del modelo — el código lo inserta como primer tramo (`dominio.tramos.insertar_recap`),
para que la invariante se cumpla aunque el LLM lo ignore. Por eso el prompt le pide los tramos
a partir del segundo 8 en los episodios que llevan recap.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from viralfarm.dominio.tramos import (
    NARRACION_MAX,
    NARRACION_MIN,
    RECAP_SEG,
    TRAMO_NARRACION_MAX,
)


class TramoLlm(BaseModel):
    tipo: str = Field(description="'original' o 'narracion'")
    inicio: float = Field(description="Segundo de inicio dentro del episodio")
    fin: float = Field(description="Segundo de fin dentro del episodio")
    texto: str = Field(default="", description="Texto a narrar; vacío en tramos 'original'")


class RespuestaGuion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    hook: str = Field(description="Frase de gancho que se superpone al principio")
    recap: str = Field(default="", description="Voz en off que sitúa a quien llega nuevo")
    tramos: list[TramoLlm]
    resumen: str = Field(description="2-3 frases de lo que se cuenta en este episodio")
    cliffhanger: str = Field(description="Tensión que queda abierta al final")
    caption: str = Field(description="Texto de publicación, sin hashtags ni número de parte")
    hashtags: list[str] = Field(description="Hashtags sin el símbolo #")


@dataclass
class DatosGuion:
    idioma_salida: str
    palabras_por_segundo: float
    parte: int
    total_partes: int
    titulo_serie: str
    duracion: float
    #: Desde dónde empiezan los tramos del modelo: 0 en la parte 1, RECAP_SEG en el resto.
    desde: float
    max_original: float
    max_palabras_recap: int
    cumbre: float | None = None
    desenlace: float | None = None


def sistema(d: DatosGuion) -> str:
    es_primero = d.parte == 1
    es_ultimo = d.parte == d.total_partes

    bloque_recap = (
        "1. RECAP: cadena vacía. Este es el primer episodio, no hay nada que recapitular."
        if es_primero
        else (
            f"1. RECAP: {RECAP_SEG:.0f} segundos de voz en off que sitúan a quien llega nuevo y\n"
            "   retoman la tensión con la que cerró la entrega anterior. Empieza POR la tensión,\n"
            f"   no por el resumen. Máximo {d.max_palabras_recap} palabras. NO forma parte de tus\n"
            f"   `tramos`: el sistema lo coloca en los primeros {RECAP_SEG:.0f} segundos."
        )
    )
    cierre = (
        "es el último episodio, así que aquí cierras la historia en vez de abrir nada."
        if es_ultimo
        else "la tensión que queda abierta al final, en una frase."
    )
    ultimo_tramo = (
        "cierra la historia y remite al perfil para ver la serie completa."
        if es_ultimo
        else "verbaliza la tensión que queda abierta y remite a la entrega siguiente. "
        "Nunca la resuelvas."
    )
    arco = ""
    if d.cumbre is not None and d.desenlace is not None:
        arco = (
            f"\n- Alrededor del segundo {d.cumbre:.0f} está el pico de tensión: deja sonar el\n"
            f"  material original ahí, no narres encima. Alrededor del {d.desenlace:.0f} se\n"
            "  cierra el arco."
        )

    return f"""Eres guionista de una SERIE vertical. Este es el EPISODIO {d.parte} de \
{d.total_partes} de "{d.titulo_serie}". El espectador puede llegar sin haber visto los
anteriores, y tiene que terminar queriendo el siguiente.

Escribes TODO el texto de salida en {d.idioma_salida}, aunque el material esté hablado en otro
idioma. En ese caso no traduces literalmente: cuentas lo que pasa a quien no lo entiende.

Escribes para este episodio:
{bloque_recap}
2. HOOK: menos de 8 palabras en pantalla. No es un resumen; es la promesa de este episodio.
   No escribas el número de parte: lo añade el sistema.
3. TRAMOS que cubren de {d.desde:.0f} a {d.duracion:.1f} segundos.
4. RESUMEN: 2-3 frases con lo que ocurre en ESTE episodio. Lo usará el recap del siguiente.
5. CLIFFHANGER: {cierre}
6. CAPTION y HASHTAGS. El caption no lleva el número de parte ni la llamada a seguir la
   cuenta: los añade el sistema.

Reglas de los tramos (episodio de {d.duracion:.0f} segundos):
- Cubren de {d.desde:.0f} a {d.duracion:.1f}, en orden, sin huecos ni solapes.
- Las fronteras de tramo caen en instantes REALES de la lista de arriba: donde entra o sale
  una línea de diálogo, donde empieza o acaba un silencio. No repartas la duración en
  números redondos —0, 15, 30, 45—: eso delata que no estás mirando el material.
- Entre 10 y 20 tramos. Un episodio de varios minutos con 3 tramos es un muro: alterna.
- Un tramo "narracion" dura entre 4 y {TRAMO_NARRACION_MAX:.0f} segundos. Más voz en off
  seguida tapa la película y el espectador se va.
- Un tramo "original" dura como mucho {d.max_original:.0f} segundos.
- La narración total ocupa entre el {NARRACION_MIN * 100:.0f} % y el \
{NARRACION_MAX * 100:.0f} % del episodio: aportas contexto, pero la película tiene que
  respirar.
- El texto narrado OCUPA su tramo, no solo cabe. A ~{d.palabras_por_segundo} palabras por
  segundo, un tramo de N segundos necesita del orden de N × {d.palabras_por_segundo}
  palabras: 12 palabras en un tramo de 16 segundos dejan doce segundos de silencio con la
  película muda debajo. Si no tienes tanto que decir, pide un tramo más corto y devuelve el
  resto a "original" — el silencio en un tramo `original` es la película; en uno `narracion`
  es un agujero.
- Los tramos "original" llevan texto vacío.
- El ÚLTIMO tramo es "narracion" de 4 a 8 segundos: {ultimo_tramo}{arco}"""


def construir_prompt(
    d: DatosGuion,
    titulo: str,
    razon: str,
    transcripcion_episodio: str,
    idioma_origen: str,
    contexto_previo: str = "",
    traduce: bool = False,
) -> str:
    aviso_traduccion = (
        f"El audio original está en {idioma_origen} y el público no lo entiende: apóyate más "
        'en tramos narrados y deja tramos "original" solo donde la imagen, la música o la '
        "emoción se expliquen sin palabras.\n\n"
        if traduce
        else ""
    )
    return f"""Episodio {d.parte} de {d.total_partes} — "{titulo}" ({d.duracion:.1f} segundos).
Por qué se eligió: {razon}
{contexto_previo}
Lo que ocurre en la pieza, en {idioma_origen} y con tiempos relativos a su inicio. Las líneas
«sin diálogo» son tramos donde no habla nadie: ahí la película está muda y tú decides si la
voz en off entra o si el material respira solo.
{transcripcion_episodio or "(sin habla)"}

{aviso_traduccion}Escribe el guion en {d.idioma_salida}. Los tramos deben cubrir de \
{d.desde:.0f} a {d.duracion:.1f} segundos."""
