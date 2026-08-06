"""Configuración del sistema.

Regla que corrige el fallo nº4 de la Fase 1 (ver `docs/arquitectura.md` §9.3): **importar este
módulo no tiene efectos**. Ni busca binarios, ni valida claves, ni toca el disco. En TypeScript
`config.ts` resolvía ffmpeg al importarse, así que cualquier módulo que importara la
configuración —incluido el cliente del LLM— exigía tener ffmpeg instalado, y eso impedía
testear nada sin él.

Aquí la resolución de binarios y de claves es **explícita y bajo demanda**: la pide quien la
necesita, cuando la necesita, y falla ahí con un mensaje accionable.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parent.parent


class ConfigVideo(BaseSettings):
    """Formato de salida vertical."""

    ancho: int = 1080
    alto: int = 1920
    fps: int = 30


class Config(BaseSettings):
    """Configuración leída de entorno y `.env`. Construirla NO valida binarios ni claves."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- rutas ---
    workspace_dir: Path = Field(default=RAIZ / "workspace")

    # --- transcripción ---
    whisper_modelo: str = "small"
    whisper_dispositivo: str = "cpu"
    #: `auto` deja que Whisper detecte. Forzar un idioma equivocado no da error: traduce sobre
    #: la marcha y devuelve texto degradado, difícil de detectar después.
    idioma_fuente: str = "auto"
    #: Vacío = el mismo idioma del audio.
    idioma_salida: str = ""

    # --- voz ---
    #: Vacío = la voz del catálogo para el idioma de salida (`dominio/idiomas.py`).
    tts_voz: str = ""

    # --- LLM ---
    llm_modelo: str = "claude-sonnet-5"
    #: Modelo con visión para la capa de comprensión.
    llm_modelo_vision: str = "claude-sonnet-5"

    # --- formato serie ---
    serie_cta: str = ""
    serie_cta_final: str = ""

    # --- montaje y render ---
    #: Atenuación del audio ambiental bajo la narración, en dB.
    ducking_db: float = -18.0
    render_crf: int = 23
    render_preset: str = "faster"
    #: Los renders fallan con errores confusos ("Failed to fetch", 500) cuando el disco se
    #: llena; se aborta antes con un mensaje claro.
    min_gb_libres: float = 8.0

    # --- binarios: vacío = buscar en PATH ---
    ffmpeg_path: str = ""
    ffprobe_path: str = ""

    video: ConfigVideo = Field(default_factory=ConfigVideo)

    # --- rutas derivadas del workspace ---

    @property
    def dir_entrada(self) -> Path:
        return self.workspace_dir / "entrada"

    @property
    def dir_trabajo(self) -> Path:
        return self.workspace_dir / "trabajo"

    @property
    def dir_cache_llm(self) -> Path:
        return self.workspace_dir / "cache-llm"

    @property
    def dir_radar(self) -> Path:
        return self.workspace_dir / "radar"


@lru_cache(maxsize=1)
def obtener_config() -> Config:
    """Configuración del proceso. Cacheada, pero construible aparte en los tests."""
    return Config()


# ---------------------------------------------------------------------------
# Resolución explícita de recursos externos. Nada de esto ocurre al importar.
# ---------------------------------------------------------------------------


class RecursoAusente(RuntimeError):
    """Falta un binario, una clave o una dependencia externa. Mensaje accionable."""


def resolver_ffmpeg(config: Config | None = None) -> str:
    """Ruta del ffmpeg **completo** del sistema.

    Nunca el que trae Remotion: es un build mínimo sin `loudnorm`, `gblur` ni `subtitles`.
    """
    config = config or obtener_config()
    if config.ffmpeg_path:
        if not Path(config.ffmpeg_path).exists():
            raise RecursoAusente(
                f"FFMPEG_PATH apunta a un archivo inexistente: {config.ffmpeg_path}"
            )
        return config.ffmpeg_path
    encontrado = shutil.which("ffmpeg")
    if not encontrado:
        raise RecursoAusente(
            "No se encontró ffmpeg. Instálalo o define FFMPEG_PATH en .env.\n"
            "Necesita ser un build completo (con loudnorm, gblur, subtitles)."
        )
    return encontrado


def resolver_ffprobe(config: Config | None = None) -> str:
    """Ruta de ffprobe. Suele venir junto a ffmpeg."""
    config = config or obtener_config()
    if config.ffprobe_path:
        if not Path(config.ffprobe_path).exists():
            raise RecursoAusente(
                f"FFPROBE_PATH apunta a un archivo inexistente: {config.ffprobe_path}"
            )
        return config.ffprobe_path

    nombre = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    vecino = Path(resolver_ffmpeg(config)).parent / nombre
    if vecino.exists():
        return str(vecino)
    encontrado = shutil.which("ffprobe")
    if not encontrado:
        raise RecursoAusente("No se encontró ffprobe (suele venir junto a ffmpeg).")
    return encontrado


def requiere_clave_anthropic() -> str:
    clave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not clave:
        raise RecursoAusente("Falta ANTHROPIC_API_KEY. Copia .env.example a .env y complétala.")
    return clave
