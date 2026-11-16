/**
 * copiar-plantillas.mjs — Copia la plantilla SVG y sus tipografías a frontend/public/plantillas/,
 * para que Vite las sirva igual en desarrollo y en build. Se ejecuta antes de dev y de build.
 * Las carpetas de origen (templates/) quedan como única fuente de verdad.
 */
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Carpeta de este script, raíz del repo y destino dentro de public/.
const aqui = dirname(fileURLToPath(import.meta.url));
const raizRepo = resolve(aqui, "..", "..");
const destino = resolve(aqui, "..", "public", "plantillas");

// Pares [origen relativo a la raíz del repo, destino relativo a public/plantillas].
const archivos = [
  [
    "templates/catalog/ig_carrusel_pasos_oscuro_6slides/template.svg",
    "ig_carrusel_pasos_oscuro_6slides/template.svg",
  ],
  [
    "templates/typography/inter/Inter-Variable.ttf",
    "typography/inter/Inter-Variable.ttf",
  ],
  [
    "templates/typography/jetbrains-mono/JetBrainsMono-Regular.ttf",
    "typography/jetbrains-mono/JetBrainsMono-Regular.ttf",
  ],
];

// Un ciclo por archivo: si falta alguno se detiene con un mensaje claro.
for (const [origen, relativo] of archivos) {
  const desde = resolve(raizRepo, origen);

  // Un origen inexistente es un error de configuración: mejor fallar aquí que servir un 404 después.
  if (!existsSync(desde)) {
    console.error(`[copiar-plantillas] No existe el archivo de origen: ${desde}`);
    process.exit(1);
  }

  // Se crea la carpeta destino si no existe y se copia el archivo.
  const hacia = resolve(destino, relativo);
  mkdirSync(dirname(hacia), { recursive: true });
  cpSync(desde, hacia);
}

console.log(`[copiar-plantillas] ${archivos.length} archivos copiados a ${destino}`);