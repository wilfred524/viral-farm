"""Medición de un guion: las cifras con las que se compara una versión de prompt con otra.

Es dominio puro —no toca disco ni red— porque es lo que hay que poder ejecutar sobre un
artefacto viejo sin volver a pagar una llamada.

Todas las métricas salen del diagnóstico de la primera serie real. Cada una responde a un
síntoma concreto que se vio en la salida:

| Métrica | Síntoma que delata |
|---|---|
| `densidad_declarada` vs `densidad_voz` | el sistema creía narrar el 38 % y narraba el 13,3 % |
| `aire_muerto` | un tramo de 16,4 s con 4,1 s de voz |
| `fronteras_redondas` | 19 de 27 fronteras eran enteros: reparto mecánico, no lectura |
| `dispersion_narrados` | 13 de 14 tramos entre 5,8 y 8,0 s: metrónomo |
| `palabras_por_tramo` | 12-16 palabras tanto en un tramo de 10,5 s como en uno de 17,7 s |

Cuando no hay `voz.json` —el caso normal al iterar sobre prompts, porque sintetizar cuesta
tiempo— la voz se **estima** a partir del ritmo de habla del idioma. Es un proxy, y se
etiqueta como tal: sirve para ordenar dos versiones de prompt, no para prometer un número.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from viralfarm.contratos.guion import Guion, Tramo
from viralfarm.contratos.voz import Voz, VozTramo
from viralfarm.dominio.tramos import (
    contar_palabras,
    densidad_real,
    detectar_aire_muerto,
)

#: Una frontera se considera "redonda" si cae a menos de esto de un segundo entero. El modelo
#: que reparte duración escribe 42.0; el que lee la transcripción escribe 41.83.
TOLERANCIA_REDONDA = 0.02


def voz_estimada(guion: Guion, palabras_por_segundo: float) -> Voz:
    """Voz sintética: cada tramo narrado dura lo que tardaría en leerse su texto.

    Permite medir aire muerto sin haber pasado por el TTS. Subestima ligeramente —el TTS mete
    pausas de puntuación— así que el aire muerto que reporta es un **suelo**: el real es
    igual o menor, nunca mayor.
    """
    tramos: list[VozTramo] = []
    for indice, tramo in enumerate(guion.tramos):
        if not tramo.texto.strip():
            continue
        segundos = contar_palabras(tramo.texto) / max(palabras_por_segundo, 0.1)
        tramos.append(
            VozTramo(
                tramo=indice,
                archivo="(estimado)",
                desplazamiento=tramo.inicio,
                duracion=max(segundos, 0.01),
            )
        )
    return Voz(voz="(estimada)", tramos=tramos)


def _es_redonda(tiempo: float) -> bool:
    return abs(tiempo - round(tiempo)) <= TOLERANCIA_REDONDA


def fronteras_redondas(tramos: Sequence[Tramo]) -> tuple[int, int]:
    """`(redondas, total)` sobre las fronteras interiores más los dos extremos."""
    tiempos = [t.inicio for t in tramos] + ([tramos[-1].fin] if tramos else [])
    return sum(1 for t in tiempos if _es_redonda(t)), len(tiempos)


@dataclass(frozen=True)
class Medida:
    """Lo medible de un episodio. Una fila de la tabla comparativa."""

    parte: int
    duracion: float
    tramos: int
    narrados: int
    #: Fracción del episodio ocupada por tramos narrados: lo que el sistema *dice* que narra.
    densidad_declarada: float
    #: Fracción realmente ocupada por voz. Con `estimada=True` es un proxy del ritmo de habla.
    densidad_voz: float
    estimada: bool
    #: Segundos dentro de tramos narrados en los que no suena nada.
    aire_muerto: float
    #: Tramos narrados donde la voz ocupa menos del mínimo (`OCUPACION_MINIMA_VOZ`).
    tramos_vacios: int
    fronteras_redondas: int
    fronteras: int
    duracion_media: float
    #: Desviación típica de la duración de los tramos narrados. Cerca de 0 = metrónomo.
    dispersion_narrados: float
    palabras_por_tramo: float
    palabras_hook: int
    palabras_recap: int

    @property
    def fraccion_redondas(self) -> float:
        return self.fronteras_redondas / self.fronteras if self.fronteras else 0.0

    @property
    def brecha_densidad(self) -> float:
        """Cuánto se equivoca el sistema sobre sí mismo. Era 0,247 en el EP0 real."""
        return self.densidad_declarada - self.densidad_voz


def medir(guion: Guion, palabras_por_segundo: float, voz: Voz | None = None) -> Medida:
    """Mide un episodio. Sin `voz`, la estima a partir del ritmo de habla del idioma."""
    estimada = voz is None
    real = voz if voz is not None else voz_estimada(guion, palabras_por_segundo)

    narrados = guion.tramos_narrados()
    duraciones = [t.duracion for t in narrados]
    palabras = [contar_palabras(t.texto) for t in narrados]
    segundos_voz = {t.tramo: t.duracion for t in real.tramos}

    aire = sum(
        max(0.0, tramo.duracion - segundos_voz.get(indice, 0.0))
        for indice, tramo in enumerate(guion.tramos)
        if tramo.texto.strip()
    )
    redondas, total_fronteras = fronteras_redondas(guion.tramos)

    return Medida(
        parte=guion.parte or guion.indice + 1,
        duracion=guion.duracion,
        tramos=len(guion.tramos),
        narrados=len(narrados),
        densidad_declarada=guion.densidad_narracion(),
        densidad_voz=densidad_real(guion.tramos, guion.duracion, real),
        estimada=estimada,
        aire_muerto=aire,
        tramos_vacios=len(detectar_aire_muerto(guion.tramos, real)),
        fronteras_redondas=redondas,
        fronteras=total_fronteras,
        duracion_media=statistics.fmean(duraciones) if duraciones else 0.0,
        dispersion_narrados=statistics.pstdev(duraciones) if len(duraciones) > 1 else 0.0,
        palabras_por_tramo=statistics.fmean(palabras) if palabras else 0.0,
        palabras_hook=contar_palabras(guion.hook),
        palabras_recap=contar_palabras(guion.recap),
    )


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------

#: Qué se muestra y cómo. El orden importa: primero lo que delata una salida vacía.
COLUMNAS: list[tuple[str, str]] = [
    ("ep", "{m.parte}"),
    ("dur", "{m.duracion:.0f}s"),
    ("tramos", "{m.tramos}"),
    ("dens.decl", "{m.densidad_declarada:.1%}"),
    ("dens.voz", "{m.densidad_voz:.1%}"),
    ("brecha", "{m.brecha_densidad:+.1%}"),
    ("aire", "{m.aire_muerto:.0f}s"),
    ("vacios", "{m.tramos_vacios}"),
    ("redondas", "{m.fraccion_redondas:.0%}"),
    ("t.medio", "{m.duracion_media:.1f}s"),
    ("dispers", "{m.dispersion_narrados:.1f}"),
    ("pal/tramo", "{m.palabras_por_tramo:.0f}"),
    ("hook", "{m.palabras_hook}"),
]


def _fila(medida: Medida) -> list[str]:
    return [formato.format(m=medida) for _, formato in COLUMNAS]


def tabla(medidas: Sequence[Medida], etiqueta: str = "") -> str:
    """Tabla de texto plano. Una fila por episodio, más el promedio."""
    if not medidas:
        return "(sin episodios que medir)"

    cabecera = [nombre for nombre, _ in COLUMNAS]
    filas = [_fila(m) for m in medidas]
    anchos = [max(len(c), *(len(f[i]) for f in filas)) for i, c in enumerate(cabecera)]

    def linea(celdas: Sequence[str]) -> str:
        return "  ".join(c.ljust(a) for c, a in zip(celdas, anchos, strict=True)).rstrip()

    salida = [linea(cabecera), linea(["-" * a for a in anchos])]
    salida += [linea(f) for f in filas]

    if any(m.estimada for m in medidas):
        salida.append("")
        salida.append("dens.voz y aire son estimados desde el ritmo de habla (no hay voz.json):")
        salida.append("el aire real es igual o menor, nunca mayor.")

    titulo = f"— {etiqueta} —\n" if etiqueta else ""
    return titulo + "\n".join(salida)


def comparar(
    antes: Sequence[Medida], despues: Sequence[Medida], etiquetas: tuple[str, str]
) -> str:
    """Las dos tablas y, debajo, la diferencia en las cifras que deciden si hubo mejora."""
    bloques = [tabla(antes, etiquetas[0]), "", tabla(despues, etiquetas[1]), ""]

    def promedio(medidas: Sequence[Medida], campo: str) -> float:
        valores = [getattr(m, campo) for m in medidas]
        return statistics.fmean(valores) if valores else 0.0

    interesantes = [
        ("densidad de voz", "densidad_voz", "{:+.1%}", True),
        ("brecha declarada-real", "brecha_densidad", "{:+.1%}", False),
        ("aire muerto por episodio", "aire_muerto", "{:+.0f}s", False),
        ("fronteras redondas", "fraccion_redondas", "{:+.0%}", False),
        ("dispersión de tramos", "dispersion_narrados", "{:+.1f}", True),
    ]

    bloques.append("— diferencia —")
    for nombre, campo, formato, subir_es_mejor in interesantes:
        delta = promedio(despues, campo) - promedio(antes, campo)
        if abs(delta) < 1e-9:
            juicio = "igual"
        else:
            juicio = "mejor" if (delta > 0) == subir_es_mejor else "peor"
        bloques.append(f"  {nombre:<26} {formato.format(delta):>8}  {juicio}")

    bloques.append("")
    bloques.append("Un refinamiento que no mueve ninguna de estas cifras probablemente")
    bloques.append("no ha cambiado nada de lo que se puede medir.")
    return "\n".join(bloques)
