// Configuración de Vite: React y copia de la plantilla SVG y sus tipografías al servidor/build.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";

export default defineConfig({
  plugins: [
    react(),
    // Cada archivo se copia por separado, con su carpeta destino explícita:
    // así no se depende de cómo el plugin conserve (o aplane) las subcarpetas.
    viteStaticCopy({
      targets: [
        {
          src: "../templates/catalog/ig_carrusel_pasos_oscuro_6slides/template.svg",
          dest: "plantillas/ig_carrusel_pasos_oscuro_6slides",
        },
        {
          src: "../templates/typography/inter/Inter-Variable.ttf",
          dest: "plantillas/typography/inter",
        },
        {
          src: "../templates/typography/jetbrains-mono/JetBrainsMono-Regular.ttf",
          dest: "plantillas/typography/jetbrains-mono",
        },
      ],
    }),
  ],
});