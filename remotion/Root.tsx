/**
 * Registro de composiciones. La duración real la aporta `calculateMetadata` a partir de las
 * props del clip, así que una misma composición sirve para clips de cualquier longitud.
 */

import React from "react";
import { Composition } from "remotion";
import { ClipVertical } from "./ClipVertical";
import type { PropsClip } from "../src/tipos";

const PROPS_EJEMPLO: PropsClip = {
  video: "ejemplo/base.mp4",
  duracion: 30,
  fps: 30,
  hook: "El detalle que nadie vio",
  subtitulos: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ClipVertical"
      component={ClipVertical}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={900}
      defaultProps={PROPS_EJEMPLO}
      calculateMetadata={({ props }) => ({
        fps: props.fps,
        durationInFrames: Math.max(1, Math.round(props.duracion * props.fps)),
      })}
    />
  );
};
