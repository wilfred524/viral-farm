/**
 * ViralFarm CLI — punto de entrada de la Fase 1.
 * Pipeline manual end-to-end: video fuente → transcripción → guion → TTS → montaje → mp4.
 *
 * Uso: npm run cli -- <comando> [opciones]
 */

const [comando] = process.argv.slice(2);

switch (comando) {
  case undefined:
  case "help":
    console.log(`ViralFarm CLI (Fase 1)

Comandos disponibles:
  help          Muestra esta ayuda
  (próximamente: ingest, transcribe, guion, tts, render)
`);
    break;
  default:
    console.error(`Comando desconocido: ${comando}. Usa "help" para ver los disponibles.`);
    process.exit(1);
}
