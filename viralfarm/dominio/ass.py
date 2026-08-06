"""Generación de subtítulos ASS — el sustituto de Remotion.

ASS (Advanced SubStation Alpha) es el formato que se inventó para karaoke: admite resaltado por
palabra, color, escala, posición y transiciones temporizadas. Cubre las tres cosas que hacía la
composición de Remotion —hook, chapa `n/N` y subtítulos karaoke— sin renderizar frame a frame
en un navegador (ver `docs/arquitectura.md` §9.2).

El karaoke NO usa las etiquetas `\\k`: esas colorean por sílaba dentro de una línea fija. Aquí
se emite **un evento por palabra activa**, con la palabra resaltada en color y escala y el
resto de su línea en blanco. Es más verboso pero da control total sobre el estilo de cada
estado, y es lo que hacen las herramientas modernas de captions animados.

Módulo puro: devuelve el contenido del archivo como texto. Quien lo escribe a disco y lo quema
con ffmpeg es el adaptador.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from viralfarm.contratos.subtitulos import OrigenSubtitulo, Subtitulo
from viralfarm.dominio.subtitulos import agrupar_en_lineas

#: Segundos que el hook permanece en pantalla.
DURACION_HOOK = 2.5
#: Duración del fundido de salida del hook, en milisegundos.
FUNDIDO_HOOK_MS = 400
#: Escala de la palabra activa, en porcentaje.
ESCALA_ACTIVA = 108


@dataclass(frozen=True)
class EstiloAss:
    """Parámetros visuales de la plantilla.

    Las fuentes se referencian por nombre y deben estar instaladas en el sistema: libass no las
    descarga. Si falta una, libass sustituye por la predeterminada sin fallar, así que conviene
    verificar el resultado la primera vez.
    """

    fuente_titular: str = "Bebas Neue"
    fuente_texto: str = "Inter"
    tamano_hook: int = 104
    tamano_chapa: int = 46
    tamano_subtitulo: int = 76
    #: Distancia del subtítulo al borde inferior, en píxeles.
    margen_inferior: int = 320
    #: Distancia del hook al borde superior, en píxeles.
    margen_superior: int = 220
    margen_lateral: int = 60
    color_texto: str = "FFFFFF"
    color_activo_original: str = "7DF9FF"
    color_activo_narracion: str = "FFE45E"
    color_chapa: str = "FFE45E"
    contorno: float = 3.0
    sombra: float = 2.0


def _color_ass(hex_rgb: str) -> str:
    """`RRGGBB` → `&H00BBGGRR&`. ASS invierte el orden de canales y antepone la transparencia."""
    limpio = hex_rgb.lstrip("#").upper()
    if len(limpio) != 6:
        raise ValueError(f"color no válido: {hex_rgb!r}; se esperaba RRGGBB")
    rr, gg, bb = limpio[0:2], limpio[2:4], limpio[4:6]
    return f"&H00{bb}{gg}{rr}&"


def _tiempo_ass(segundos: float) -> str:
    """`H:MM:SS.cc` — ASS trabaja en centésimas y con una sola cifra de hora."""
    segundos = max(0.0, segundos)
    centesimas = round(segundos * 100)
    horas, resto = divmod(centesimas, 360000)
    minutos, resto = divmod(resto, 6000)
    segs, cent = divmod(resto, 100)
    return f"{horas}:{minutos:02d}:{segs:02d}.{cent:02d}"


def _escapar(texto: str) -> str:
    """Neutraliza lo que ASS interpreta como marcado."""
    return (
        texto.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _cabecera(ancho: int, alto: int, estilo: EstiloAss) -> str:
    negro = "&H00000000&"
    # WrapStyle 2: sin ajuste automático de línea; el corte lo decide `agrupar_en_lineas`.
    # Alignment 2 = abajo centrado, 8 = arriba centrado.
    return f"""[Script Info]
; Generado por ViralFarm — no editar a mano
ScriptType: v4.00+
PlayResX: {ancho}
PlayResY: {alto}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, \
Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, \
Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{estilo.fuente_titular},{estilo.tamano_hook},{_color_ass(estilo.color_texto)},\
{_color_ass(estilo.color_texto)},{negro},{negro},0,0,0,0,100,100,0,0,1,{estilo.contorno},\
{estilo.sombra},8,{estilo.margen_lateral},{estilo.margen_lateral},{estilo.margen_superior},1
Style: Chapa,{estilo.fuente_titular},{estilo.tamano_chapa},{_color_ass(estilo.color_chapa)},\
{_color_ass(estilo.color_chapa)},{negro},{negro},0,0,0,0,100,100,2,0,1,{estilo.contorno},\
{estilo.sombra},8,{estilo.margen_lateral},{estilo.margen_lateral},\
{max(0, estilo.margen_superior - estilo.tamano_hook - 40)},1
Style: Subtitulo,{estilo.fuente_texto},{estilo.tamano_subtitulo},\
{_color_ass(estilo.color_texto)},{_color_ass(estilo.color_texto)},{negro},{negro},\
-1,0,0,0,100,100,0,0,1,{estilo.contorno},{estilo.sombra},2,{estilo.margen_lateral},\
{estilo.margen_lateral},{estilo.margen_inferior},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _dialogo(inicio: float, fin: float, estilo: str, texto: str, capa: int = 0) -> str:
    return f"Dialogue: {capa},{_tiempo_ass(inicio)},{_tiempo_ass(fin)},{estilo},,0,0,0,,{texto}"


def _eventos_hook(
    hook: str, parte: int | None, total_partes: int | None, estilo: EstiloAss
) -> list[str]:
    eventos: list[str] = []
    if not hook.strip():
        return eventos

    fundido = f"{{\\fad(200,{FUNDIDO_HOOK_MS})}}"
    eventos.append(_dialogo(0.0, DURACION_HOOK, "Hook", f"{fundido}{_escapar(hook)}", capa=2))

    # La chapa va como evento propio y no concatenada al hook: con 104 px de tipografía, meter
    # "Parte 3 · " dentro rompería el encaje de la caja.
    if parte is not None and total_partes is not None:
        eventos.append(
            _dialogo(
                0.0,
                DURACION_HOOK,
                "Chapa",
                f"{fundido}{parte} / {total_partes}",
                capa=2,
            )
        )
    return eventos


def _eventos_subtitulos(subtitulos: Sequence[Subtitulo], estilo: EstiloAss) -> list[str]:
    """Un evento por palabra activa: la palabra resaltada, el resto de su línea en blanco."""
    eventos: list[str] = []

    for linea in agrupar_en_lineas(subtitulos):
        if not linea:
            continue
        color_activo = (
            estilo.color_activo_narracion
            if linea[0].origen is OrigenSubtitulo.NARRACION
            else estilo.color_activo_original
        )
        resalte = f"\\c{_color_ass(color_activo)}\\fscx{ESCALA_ACTIVA}\\fscy{ESCALA_ACTIVA}"
        normal = f"\\c{_color_ass(estilo.color_texto)}\\fscx100\\fscy100"

        for i, palabra in enumerate(linea):
            # La palabra sigue en pantalla hasta que entra la siguiente: sin esto la línea
            # parpadearía en los huecos entre palabras.
            fin = linea[i + 1].inicio if i + 1 < len(linea) else linea[-1].fin
            if fin <= palabra.inicio:
                continue

            partes = [
                f"{{{resalte if j == i else normal}}}{_escapar(p.texto)}"
                for j, p in enumerate(linea)
            ]
            eventos.append(_dialogo(palabra.inicio, fin, "Subtitulo", " ".join(partes)))

    return eventos


def generar_ass(
    hook: str,
    subtitulos: Sequence[Subtitulo],
    ancho: int = 1080,
    alto: int = 1920,
    parte: int | None = None,
    total_partes: int | None = None,
    estilo: EstiloAss | None = None,
) -> str:
    """Contenido completo del archivo `.ass` del episodio."""
    estilo = estilo or EstiloAss()
    lineas = [_cabecera(ancho, alto, estilo).rstrip("\n")]
    lineas.extend(_eventos_hook(hook, parte, total_partes, estilo))
    lineas.extend(_eventos_subtitulos(subtitulos, estilo))
    return "\n".join(lineas) + "\n"
