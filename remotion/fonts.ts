/**
 * Carga de fuentes a nivel de módulo, limitando pesos y subsets para no disparar peticiones
 * de red durante el render.
 */

import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadBebas } from "@remotion/google-fonts/BebasNeue";

export const { fontFamily: fuenteTexto } = loadInter("normal", {
  weights: ["600", "800"],
  subsets: ["latin"],
});

export const { fontFamily: fuenteTitular } = loadBebas("normal", {
  weights: ["400"],
  subsets: ["latin"],
});
