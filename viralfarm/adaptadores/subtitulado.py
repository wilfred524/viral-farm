"""Quemado de subtítulos ASS sobre el episodio montado — el sustituto de Remotion.

`dominio/ass.py` produce el texto del archivo `.ass`; este adaptador lo escribe a disco y
llama a ffmpeg con el filtro `subtitles`, que lo rasteriza con libass.

Dos cosas que en Remotion venían resueltas y aquí hay que resolver a mano:

- **Las fuentes.** libass no descarga nada: busca por nombre entre las instaladas en el
  sistema y, si no encuentra la que pides, **sustituye en silencio** por la
  predeterminada. Un render que se ve bien en una máquina saldría con otra tipografía en
  la siguiente. Por eso las TTF viven en `assets/fonts/` y se le pasa `fontsdir`: el
  resultado deja de depender de lo que haya instalado.
- **El escapado de la ruta.** El filtro `subtitles=` recibe la ruta *dentro* de una
  cadena de filtros, así que los dos puntos de `C:\\…` y las barras invertidas de Windows
  hay que escaparlos o ffmpeg parte el filtro por la mitad.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from viralfarm.adaptadores.proceso import ErrorProceso, ejecutar

#: Fuentes empaquetadas con el proyecto, para que el render sea reproducible.
DIR_FUENTES = Path(__file__).resolve().parent.parent.parent / "assets" / "fonts"

#: Calidad del episodio terminado. crf 23 es indistinguible de 18 en un móvil y ocupa la
#: mitad; el material ya viene comprimido una vez desde el montaje.
CRF_FINAL = 23
PRESET_FINAL = "faster"

#: El preview va a Telegram, que corta la subida en 50 MB.
CRF_PREVIEW = 30
ALTO_PREVIEW = 1280
ANCHO_PREVIEW = 720


#: Raíz del proyecto: se usa como directorio de trabajo de ffmpeg para que las rutas del
#: filtro puedan ser relativas.
RAIZ = Path(__file__).resolve().parent.parent.parent


def _ruta_para_filtro(ruta: Path, base: Path) -> str:
    """Ruta utilizable **dentro** de una cadena de filtros de ffmpeg.

    Dentro de un filtro, `:` separa argumentos y `\\` escapa, así que una ruta de Windows
    (`C:\\a\\b.ass`) parte el filtro por la mitad. Escapar los dos puntos funciona con un
    solo argumento, pero vuelve a fallar en cuanto se encadena un segundo
    (`subtitles=…:fontsdir=…`), que fue exactamente el error al probarlo.

    La salida limpia es no meter nunca una unidad de disco en el filtro: ffmpeg se lanza
    con `cwd` en la raíz del proyecto y aquí se devuelve la ruta **relativa** a ella. Si
    el archivo cae fuera del proyecto se recurre al escape, que sigue sirviendo para el
    caso de un solo argumento.
    """
    try:
        return ruta.resolve().relative_to(base).as_posix()
    except ValueError:
        return str(ruta).replace("\\", "/").replace(":", r"\:")


@dataclass
class ResultadoSubtitulado:
    final: Path
    preview: Path | None
    ass: Path


class Subtitulador:
    """Quema subtítulos y produce el episodio publicable."""

    def __init__(
        self, ffmpeg: str, dir_fuentes: Path | None = None, cwd: Path | None = None
    ) -> None:
        self.ffmpeg = ffmpeg
        self.dir_fuentes = dir_fuentes or DIR_FUENTES
        #: Directorio desde el que se lanza ffmpeg. Ver `_ruta_para_filtro`.
        self.cwd = cwd or RAIZ

    def _filtro(self, ass: Path) -> str:
        partes = [f"subtitles={_ruta_para_filtro(ass, self.cwd)}"]
        if self.dir_fuentes.is_dir():
            partes.append(f"fontsdir={_ruta_para_filtro(self.dir_fuentes, self.cwd)}")
        return ":".join(partes)

    def quemar(
        self,
        base: Path,
        contenido_ass: str,
        salida: Path,
        preview: Path | None = None,
        on_progreso: Callable[[str], None] | None = None,
    ) -> ResultadoSubtitulado:
        """Rasteriza los subtítulos sobre `base` y escribe el episodio terminado.

        El `.ass` se conserva junto a la salida a propósito: es texto plano, así que un
        problema de sincronía o de estilo se diagnostica leyéndolo, sin volver a renderizar.
        """
        if not base.exists():
            raise FileNotFoundError(f"Falta el montaje base: {base}")

        salida.parent.mkdir(parents=True, exist_ok=True)
        ruta_ass = salida.with_suffix(".ass")
        ruta_ass.write_text(contenido_ass, encoding="utf-8")

        if not self.dir_fuentes.is_dir():
            raise FileNotFoundError(
                f"No están las tipografías en {self.dir_fuentes}. Sin ellas libass "
                "sustituye por la fuente por defecto y el episodio sale con otra "
                "tipografía, sin avisar."
            )

        ejecutar(
            self.ffmpeg,
            [
                "-y",
                "-i", str(base),
                "-vf", self._filtro(ruta_ass),
                "-c:v", "libx264",
                "-preset", PRESET_FINAL,
                "-crf", str(CRF_FINAL),
                "-pix_fmt", "yuv420p",
                # El audio ya viene mezclado del montaje: copiarlo evita una segunda
                # recompresión que solo restaría calidad.
                "-c:a", "copy",
                "-movflags", "+faststart",
                str(salida),
            ],
            etiqueta="ffmpeg (subtítulos)",
            cwd=str(self.cwd),
            on_stderr=on_progreso,
        )

        ruta_preview = None
        if preview is not None:
            self.comprimir_preview(salida, preview)
            ruta_preview = preview

        return ResultadoSubtitulado(final=salida, preview=ruta_preview, ass=ruta_ass)

    def comprimir_preview(self, entrada: Path, salida: Path) -> None:
        """Versión ligera para la aprobación por Telegram (límite de 50 MB de la Bot API)."""
        salida.parent.mkdir(parents=True, exist_ok=True)
        ejecutar(
            self.ffmpeg,
            [
                "-y", "-i", str(entrada),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", str(CRF_PREVIEW),
                "-vf", f"scale={ANCHO_PREVIEW}:{ALTO_PREVIEW}",
                "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart",
                str(salida),
            ],
            etiqueta="ffmpeg (preview)",
        )


def cargar_subtitulador(ffmpeg: str | None = None) -> Subtitulador:
    """Construye el subtitulador con el ffmpeg del sistema."""
    if ffmpeg is None:
        from viralfarm.config import resolver_ffmpeg

        ffmpeg = resolver_ffmpeg()
    if not shutil.which(ffmpeg) and not Path(ffmpeg).exists():
        raise FileNotFoundError(f"No se encontró ffmpeg en {ffmpeg}")
    return Subtitulador(ffmpeg)


__all__ = ["ErrorProceso", "ResultadoSubtitulado", "Subtitulador", "cargar_subtitulador"]
