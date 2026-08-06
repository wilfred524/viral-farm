/**
 * Composición del clip vertical: el `base.mp4` que ya trae el reencuadre y la mezcla de
 * audio, con el hook superpuesto al principio y los subtítulos karaoke encima.
 *
 * `OffthreadVideo` no debe envolverse en efectos que refetchean sub-frames
 * (CameraMotionBlur/Trail): falla el refetch. Los efectos van en capas hermanas.
 */

import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Subtitulos } from "./Subtitulos";
import { fuenteTitular } from "./fonts";
import type { PropsClip } from "../src/tipos";

/** Segundos que el hook permanece en pantalla. */
const DURACION_HOOK = 2.5;

/**
 * Chapa de numeración de la serie. Va aparte del hook y no concatenada a su texto: con 104 px
 * de tipografía, meter "Parte 3 · " dentro rompería el encaje de la caja.
 */
const ChapaParte: React.FC<{ parte: number; totalPartes: number }> = ({ parte, totalPartes }) => (
  <div
    style={{
      marginBottom: 18,
      padding: "10px 28px",
      borderRadius: 999,
      background: "rgba(0,0,0,0.55)",
      fontFamily: fuenteTitular,
      fontSize: 46,
      letterSpacing: 2,
      color: "#FFE45E",
      textShadow: "0 4px 18px rgba(0,0,0,0.7)",
    }}
  >
    {parte} / {totalPartes}
  </div>
);

const Hook: React.FC<{ texto: string; parte?: number; totalPartes?: number }> = ({
  texto,
  parte,
  totalPartes,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrada = spring({ frame, fps, config: { damping: 14, mass: 0.6 } });
  const salida = interpolate(
    frame,
    [(DURACION_HOOK - 0.4) * fps, DURACION_HOOK * fps],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  if (salida <= 0) return null;

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-start",
        alignItems: "center",
        paddingTop: 220,
        opacity: salida,
      }}
    >
      {parte !== undefined && totalPartes !== undefined ? (
        <ChapaParte parte={parte} totalPartes={totalPartes} />
      ) : null}
      <div
        style={{
          transform: `scale(${0.9 + entrada * 0.1})`,
          maxWidth: 900,
          padding: "24px 40px",
          borderRadius: 28,
          background: "rgba(0,0,0,0.55)",
          fontFamily: fuenteTitular,
          fontSize: 104,
          lineHeight: 1.02,
          color: "#FFFFFF",
          textAlign: "center",
          textShadow: "0 8px 30px rgba(0,0,0,0.6)",
        }}
      >
        {texto}
      </div>
    </AbsoluteFill>
  );
};

export const ClipVertical: React.FC<PropsClip> = ({
  video,
  hook,
  subtitulos,
  parte,
  totalPartes,
}) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      <OffthreadVideo src={staticFile(video)} />
      <Hook texto={hook} parte={parte} totalPartes={totalPartes} />
      <Subtitulos subtitulos={subtitulos} />
    </AbsoluteFill>
  );
};
