/**
 * Subtítulos karaoke: la palabra que suena en este frame se resalta.
 *
 * Las palabras vienen de dos orígenes y se distinguen visualmente: las del audio original
 * (lo que dicen en el video) y las de la narración generada. Ver `origen` en `Subtitulo`.
 */

import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { fuenteTexto } from "./fonts";
import type { Subtitulo } from "../src/tipos";

/** Palabras por línea: suficiente para leer de un vistazo sin tapar la imagen. */
const PALABRAS_POR_LINEA = 4;

interface Props {
  subtitulos: Subtitulo[];
}

function agruparEnLineas(subtitulos: Subtitulo[]): Subtitulo[][] {
  const lineas: Subtitulo[][] = [];
  for (let i = 0; i < subtitulos.length; i += PALABRAS_POR_LINEA) {
    lineas.push(subtitulos.slice(i, i + PALABRAS_POR_LINEA));
  }
  return lineas;
}

export const Subtitulos: React.FC<Props> = ({ subtitulos }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const lineas = React.useMemo(() => agruparEnLineas(subtitulos), [subtitulos]);
  const linea = lineas.find((l) => t >= (l[0]?.inicio ?? 0) && t <= (l[l.length - 1]?.fin ?? 0));
  if (!linea || linea.length === 0) return null;

  const esNarracion = linea[0]?.origen === "narracion";

  return (
    <div
      style={{
        position: "absolute",
        bottom: 320,
        left: 60,
        right: 60,
        display: "flex",
        flexWrap: "wrap",
        justifyContent: "center",
        gap: "0 18px",
        fontFamily: fuenteTexto,
        fontWeight: 800,
        fontSize: 76,
        lineHeight: 1.15,
        textAlign: "center",
      }}
    >
      {linea.map((palabra, i) => {
        const activa = t >= palabra.inicio && t <= palabra.fin;
        return (
          <span
            key={`${palabra.inicio}-${i}`}
            style={{
              color: activa ? (esNarracion ? "#FFE45E" : "#7DF9FF") : "#FFFFFF",
              textShadow: "0 6px 24px rgba(0,0,0,0.85), 0 0 4px rgba(0,0,0,0.9)",
              transform: activa ? "scale(1.08)" : "scale(1)",
              display: "inline-block",
            }}
          >
            {palabra.texto}
          </span>
        );
      })}
    </div>
  );
};
