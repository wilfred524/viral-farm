"""`python -m viralfarm.banco` — comparar dos versiones de prompt sobre el mismo material.

    python -m viralfarm.banco generar media/pelicula-prueba-05-25-12e8a388 --episodios 2
    python -m viralfarm.banco medir media/banco/8f21ab03+bb2d2ea0
    python -m viralfarm.banco comparar media/banco/<version-a> media/banco/<version-b>

`generar` escribe los guiones en `media/banco/<hash-sistema>+<hash-usuario>/`, de modo que la
carpeta **es** la versión: editar un `.md` y volver a generar produce otra carpeta, y las dos
quedan comparables sin llevar la cuenta a mano. Si la carpeta ya existe no se vuelve a llamar
al modelo, así que medir y comparar son gratis.

Coste: una llamada por episodio. Con DeepSeek, céntimos por comparación.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from viralfarm.adaptadores.llm import ErrorLlm, cargar_cliente
from viralfarm.banco.metricas import Medida, comparar, medir, tabla
from viralfarm.contratos.comunes import Procedencia
from viralfarm.contratos.fuente import Fuente
from viralfarm.contratos.guion import Guion
from viralfarm.contratos.legado import fuente_desde_legado, serie_desde_legado
from viralfarm.contratos.serie import Episodio, Serie
from viralfarm.contratos.transcripcion import Transcripcion
from viralfarm.dominio import episodios as dom_episodios
from viralfarm.dominio.guion import ensamblar
from viralfarm.dominio.idiomas import Idioma, resolver_idioma
from viralfarm.dominio.timeline import (
    construir_timeline,
    formatear_para_prompt,
    recortar_a_episodio,
)
from viralfarm.dominio.tramos import max_palabras_recap
from viralfarm.prompts import guion as prompt_guion
from viralfarm.prompts.serie import RespuestaSerie

DIR_BANCO = Path("media/banco")

#: Cuánto material original seguido se tolera sin voz en un episodio del banco. Es el mismo
#: valor que usa el paso de guion; vive aquí para no importar el paso, que aún no existe.
MAX_ORIGINAL = 35.0


class MaterialAusente(FileNotFoundError):
    """Falta un artefacto necesario. El mensaje dice cuál y cómo obtenerlo."""


T = TypeVar("T", bound=BaseModel)


def _leer(modelo: type[T], ruta: Path, como_obtenerlo: str) -> T:
    if not ruta.exists():
        raise MaterialAusente(f"No existe {ruta}. {como_obtenerlo}")
    return modelo.model_validate_json(ruta.read_text(encoding="utf-8"))


def _cargar_fuente(dir_video: Path) -> Fuente:
    """`fuente.json`, en formato Python o en el camelCase del pipeline TypeScript."""
    ruta = dir_video / "fuente.json"
    if not ruta.exists():
        raise MaterialAusente(f"No existe {ruta}. Ingesta el vídeo primero.")
    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    if "videoId" in crudo:
        return fuente_desde_legado(crudo)
    return Fuente.model_validate(crudo)


def _cargar_serie(dir_video: Path, transcripcion: Transcripcion, duracion: float) -> Serie:
    """Serie normalizada a partir de `serie.json`, o del `clips.json` del pipeline TypeScript.

    Aceptar el `clips.json` viejo no es cortesía: es lo que permite comparar prompts de guion
    sobre exactamente los mismos cortes que produjo la primera serie real, sin volver a pagar
    la llamada de cortes ni introducir una segunda variable en la comparación.
    """
    ruta_serie = dir_video / "serie.json"
    if ruta_serie.exists():
        return Serie.model_validate_json(ruta_serie.read_text(encoding="utf-8"))

    ruta_clips = dir_video / "clips.json"
    if not ruta_clips.exists():
        raise MaterialAusente(
            f"No existe {ruta_clips}. Genera antes los cortes, o copia el clips.json de una "
            "ejecución previa."
        )
    datos = json.loads(ruta_clips.read_text(encoding="utf-8"))
    # El `clips.json` del pipeline TypeScript ya venía normalizado y trae sus propios cortes
    # reparados: se respeta tal cual, para no comparar dos prompts sobre episodios distintos.
    if "clips" in datos:
        return serie_desde_legado(datos)

    crudo = RespuestaSerie.model_validate(datos)
    propuestos = [
        dom_episodios.EpisodioPropuesto(
            inicio=e.inicio,
            fin=e.fin,
            titulo=e.titulo,
            razon=e.razon,
            cumbre=e.cumbre,
            desenlace=e.desenlace,
            resumen=e.resumen,
            cliffhanger=e.cliffhanger,
            puntuacion=e.puntuacion,
        )
        for e in crudo.episodios
    ]
    resultado = dom_episodios.normalizar_episodios(propuestos, transcripcion.segmentos, duracion)
    for aviso in resultado.avisos:
        print(f"  · {aviso}", file=sys.stderr)
    return Serie(
        modelo="(desde clips.json)",
        titulo=crudo.titulo_serie,
        sinopsis=crudo.sinopsis,
        cobertura=resultado.cobertura,
        episodios=resultado.episodios,
    )


def _datos(episodio: Episodio, total_partes: int, idioma: Idioma) -> prompt_guion.DatosGuion:
    parte = episodio.parte or episodio.indice + 1
    arco = episodio.arco
    return prompt_guion.DatosGuion(
        idioma_salida=idioma.nombre,
        palabras_por_segundo=idioma.palabras_por_segundo,
        parte=parte,
        total_partes=total_partes,
        titulo_serie=episodio.titulo,
        duracion=episodio.duracion,
        desde=0.0 if parte == 1 else 8.0,
        max_original=MAX_ORIGINAL,
        max_palabras_recap=max_palabras_recap(idioma.palabras_por_segundo),
        cumbre=arco.cumbre if arco else None,
        desenlace=arco.desenlace if arco else None,
        arco_estimado=episodio.arco_estimado,
    )


def generar(dir_video: Path, limite: int, idioma_salida: str, force: bool) -> Path:
    """Regenera los guiones de los primeros `limite` episodios con el prompt actual."""
    fuente = _cargar_fuente(dir_video)
    transcripcion = _leer(
        Transcripcion, dir_video / "transcripcion.json", "Transcribe el vídeo primero."
    )
    serie = _cargar_serie(dir_video, transcripcion, fuente.duracion)
    idioma = resolver_idioma(idioma_salida)
    origen = resolver_idioma(transcripcion.idioma)

    version = Procedencia(
        prompt_sistema=prompt_guion.version_sistema(),
        prompt_usuario=prompt_guion.version_usuario(),
    )
    destino = DIR_BANCO / version.etiqueta
    if destino.exists() and not force:
        print(f"Ya existe {destino}: se mide lo que hay. Usa --force para regenerar.")
        return destino

    cliente = cargar_cliente()
    timeline = construir_timeline(transcripcion, fuente.duracion)
    destino.mkdir(parents=True, exist_ok=True)

    episodios = serie.episodios[:limite]
    contexto = ""
    for episodio in episodios:
        datos = _datos(episodio, len(serie.episodios), idioma)
        recorte = recortar_a_episodio(timeline, episodio.inicio, episodio.fin)
        prompt = prompt_guion.construir_prompt(
            datos,
            titulo=episodio.titulo,
            razon=episodio.razon,
            transcripcion_episodio=formatear_para_prompt(recorte),
            idioma_origen=origen.nombre,
            contexto_previo=contexto,
            traduce=origen.codigo != idioma.codigo,
        )
        print(f"  parte {datos.parte}/{datos.total_partes}…", flush=True)
        respuesta = cliente.pedir_estructurado(
            prompt_guion.RespuestaGuion,
            prompt_guion.sistema(datos),
            prompt,
            f"banco guion parte {datos.parte}",
        )
        procedencia = version.model_copy(update={"modelo": getattr(cliente, "modelo", "")})
        resultado = ensamblar(respuesta, episodio, idioma, len(serie.episodios), procedencia)
        for aviso in resultado.avisos:
            print(f"    · {aviso}", file=sys.stderr)

        ruta = destino / f"guion-parte-{datos.parte}.json"
        ruta.write_text(resultado.guion.model_dump_json(indent=2), encoding="utf-8")
        contexto = resultado.guion.resumen

    print(f"\n{len(episodios)} guiones en {destino}")
    return destino


def _guion_desde_respuesta(
    ruta: Path, indice: int, dir_video: Path, idioma_salida: str
) -> Guion:
    """Ensambla una respuesta cruda del LLM contra el material de su vídeo.

    Es lo que permite medir las salidas del pipeline TypeScript —que guardaba la respuesta
    tal cual, sin ensamblar— y comprobar que el banco **reproduce el diagnóstico**: si no
    saca el 13,3 % de densidad real del episodio 1, la medición está mal, no el guion.
    """
    fuente = _cargar_fuente(dir_video)
    transcripcion = _leer(
        Transcripcion, dir_video / "transcripcion.json", "Transcribe el vídeo primero."
    )
    serie = _cargar_serie(dir_video, transcripcion, fuente.duracion)
    if indice >= len(serie.episodios):
        raise MaterialAusente(
            f"{ruta.name} es la parte {indice + 1}, pero la serie solo tiene "
            f"{len(serie.episodios)} episodios."
        )

    respuesta = _leer(prompt_guion.RespuestaGuion, ruta, "")
    idioma = resolver_idioma(idioma_salida)
    return ensamblar(
        respuesta, serie.episodios[indice], idioma, len(serie.episodios)
    ).guion


def _medidas(directorio: Path, idioma_salida: str, material: Path | None = None) -> list[Medida]:
    rutas = sorted(directorio.glob("guion-parte-*.json"), key=lambda p: int(p.stem.split("-")[-1]))
    if not rutas:
        raise MaterialAusente(f"No hay guiones en {directorio} (se buscan guion-parte-*.json).")

    pps = resolver_idioma(idioma_salida).palabras_por_segundo
    medidas: list[Medida] = []
    for indice, ruta in enumerate(rutas):
        try:
            guion = Guion.model_validate_json(ruta.read_text(encoding="utf-8"))
        except ValidationError:
            if material is None:
                raise MaterialAusente(
                    f"{ruta} no es un guion ensamblado, sino la respuesta cruda del modelo. "
                    "Pasa --material <dir del vídeo> para ensamblarla contra su serie."
                ) from None
            guion = _guion_desde_respuesta(ruta, indice, material, idioma_salida)
        medidas.append(medir(guion, pps))
    return medidas


def main(argv: list[str] | None = None) -> int:
    padre = argparse.ArgumentParser(add_help=False)
    padre.add_argument("--idioma-salida", default="en", help="Idioma del contenido generado")

    parser = argparse.ArgumentParser(prog="viralfarm.banco", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    p_gen = sub.add_parser("generar", parents=[padre], help="Regenera con el prompt actual")
    p_gen.add_argument("dir_video", type=Path)
    p_gen.add_argument("--episodios", type=int, default=2, help="Cuántos episodios (coste)")
    p_gen.add_argument("--force", action="store_true", help="Rehace aunque la versión exista")

    p_med = sub.add_parser("medir", parents=[padre], help="Tabla de un directorio de guiones")
    p_med.add_argument("directorio", type=Path)
    p_med.add_argument(
        "--material",
        type=Path,
        help="Directorio del vídeo, si los archivos son respuestas crudas sin ensamblar",
    )

    p_cmp = sub.add_parser("comparar", parents=[padre], help="Dos versiones, lado a lado")
    p_cmp.add_argument("antes", type=Path)
    p_cmp.add_argument("despues", type=Path)
    p_cmp.add_argument("--material", type=Path, help="Ver `medir --material`")

    args = parser.parse_args(argv)

    try:
        if args.comando == "generar":
            destino = generar(args.dir_video, args.episodios, args.idioma_salida, args.force)
            print()
            print(tabla(_medidas(destino, args.idioma_salida), destino.name))
        elif args.comando == "medir":
            medidas = _medidas(args.directorio, args.idioma_salida, args.material)
            print(tabla(medidas, args.directorio.name))
        else:
            print(
                comparar(
                    _medidas(args.antes, args.idioma_salida, args.material),
                    _medidas(args.despues, args.idioma_salida, args.material),
                    (args.antes.name, args.despues.name),
                )
            )
    except (MaterialAusente, ErrorLlm) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
