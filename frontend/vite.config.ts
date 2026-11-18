// Configuración de Vite: React, acceso a contracts/ y proxy hacia el backend.
// La plantilla SVG y las tipografías llegan por public/plantillas, que llena
// scripts/copiar-plantillas.mjs antes de dev y build.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // import.meta.glob de grabacion.ts lee contracts/recordings, fuera de frontend/:
    // el servidor de desarrollo debe poder servir la carpeta superior.
    fs: { allow: [".."] },
    // Las llamadas a /api van al backend (uvicorn en el puerto 8000): sin CORS en desarrollo
    // y con el mismo origen que tendrá el despliegue con Nginx.
    proxy: {
      "/api": {
        // 127.0.0.1 y no "localhost": Node puede resolver localhost a ::1 (IPv6)
        // y uvicorn escucha en IPv4, lo que daría ECONNREFUSED.
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});