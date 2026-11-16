// Configuración de Vite: React y acceso a contracts/. La plantilla SVG y las tipografías
// llegan por public/plantillas, que llena scripts/copiar-plantillas.mjs antes de dev y build.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // import.meta.glob de grabacion.ts lee contracts/recordings, fuera de frontend/:
    // el servidor de desarrollo debe poder servir la carpeta superior.
    fs: { allow: [".."] },
  },
});