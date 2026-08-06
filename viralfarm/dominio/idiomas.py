"""Catálogo de idiomas.

Hay dos idiomas en juego y NO tienen por qué coincidir:

- **idioma fuente**: el que se habla en el material. Lo detecta Whisper (`auto`) o se fuerza.
- **idioma de salida**: en el que se escriben narración, hook, caption y hashtags. Por defecto
  hereda del fuente; se cambia para producir contenido para otro mercado.

Cada idioma aporta además la voz de Edge-TTS y su ritmo de habla, que es lo que decide cuánto
texto cabe en un tramo narrado.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

#: Voz multilingüe: red para cualquier idioma que no esté en el catálogo.
VOZ_FALLBACK = "en-US-AndrewMultilingualNeural"

#: Ritmo conservador para idiomas sin afinar.
PALABRAS_POR_SEGUNDO_FALLBACK = 2.6


@dataclass(frozen=True)
class TextosSerie:
    """Textos del formato serie que compone el código, no el modelo.

    Van en el idioma de salida: un caption en inglés rematado con "Sígueme" delata que detrás
    hay una plantilla.
    """

    #: Recibe número de parte y total: "Parte 2/8".
    parte: Callable[[int, int], str]
    cta: str
    cta_final: str


@dataclass(frozen=True)
class Idioma:
    #: Código ISO 639-1 en minúsculas.
    codigo: str
    #: Nombre en español, para los prompts.
    nombre: str
    #: Voz de Edge-TTS por defecto (`edge-tts --list-voices` lista el resto).
    voz: str
    #: Ritmo de habla de esa voz, en palabras por segundo.
    palabras_por_segundo: float
    serie: TextosSerie


CATALOGO: dict[str, Idioma] = {
    "es": Idioma(
        codigo="es",
        nombre="español",
        voz="es-MX-JorgeNeural",
        palabras_por_segundo=2.6,
        serie=TextosSerie(
            parte=lambda n, total: f"Parte {n}/{total}",
            cta="Sígueme para no perderte la parte siguiente.",
            cta_final="Serie completa en el perfil.",
        ),
    ),
    "en": Idioma(
        codigo="en",
        nombre="inglés",
        voz="en-US-AndrewNeural",
        palabras_por_segundo=2.9,
        serie=TextosSerie(
            parte=lambda n, total: f"Part {n}/{total}",
            cta="Follow so you don't miss the next part.",
            cta_final="Full series on my profile.",
        ),
    ),
    "pt": Idioma(
        codigo="pt",
        nombre="portugués",
        voz="pt-BR-AntonioNeural",
        palabras_por_segundo=2.6,
        serie=TextosSerie(
            parte=lambda n, total: f"Parte {n}/{total}",
            cta="Me siga para não perder a próxima parte.",
            cta_final="Série completa no perfil.",
        ),
    ),
    "fr": Idioma(
        codigo="fr",
        nombre="francés",
        voz="fr-FR-HenriNeural",
        palabras_por_segundo=2.7,
        serie=TextosSerie(
            parte=lambda n, total: f"Partie {n}/{total}",
            cta="Abonne-toi pour ne pas rater la suite.",
            cta_final="Série complète sur le profil.",
        ),
    ),
    "it": Idioma(
        codigo="it",
        nombre="italiano",
        voz="it-IT-DiegoNeural",
        palabras_por_segundo=2.7,
        serie=TextosSerie(
            parte=lambda n, total: f"Parte {n}/{total}",
            cta="Seguimi per non perderti la prossima parte.",
            cta_final="Serie completa sul profilo.",
        ),
    ),
    "de": Idioma(
        codigo="de",
        nombre="alemán",
        voz="de-DE-ConradNeural",
        palabras_por_segundo=2.4,
        serie=TextosSerie(
            parte=lambda n, total: f"Teil {n}/{total}",
            cta="Folge mir, damit du den nächsten Teil nicht verpasst.",
            cta_final="Komplette Serie im Profil.",
        ),
    ),
}


def normalizar_codigo(codigo: str | None) -> str:
    """`en-US`, `EN`, `en_us` → `en`. Cadena vacía si no hay código."""
    if not codigo:
        return ""
    return codigo.strip().lower().replace("_", "-").split("-")[0]


def resolver_idioma(codigo: str | None) -> Idioma:
    """Resuelve un código a su entrada del catálogo.

    Un idioma desconocido no es un error: Whisper reconoce muchos más de los que aquí se
    afinan, así que se cae a la voz multilingüe con un ritmo conservador.
    """
    base = normalizar_codigo(codigo)
    conocido = CATALOGO.get(base)
    if conocido is not None:
        return conocido
    return Idioma(
        codigo=base or "desconocido",
        nombre=base or "desconocido",
        voz=VOZ_FALLBACK,
        palabras_por_segundo=PALABRAS_POR_SEGUNDO_FALLBACK,
        serie=CATALOGO["en"].serie,
    )


def es_idioma_conocido(codigo: str | None) -> bool:
    """True si el idioma tiene voz y ritmo afinados en el catálogo."""
    return normalizar_codigo(codigo) in CATALOGO


def idiomas_soportados() -> list[str]:
    return sorted(CATALOGO)
