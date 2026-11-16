/**
 * main.tsx — Punto de entrada: monta la aplicación React en #root.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { App } from "./App.tsx";

const raiz = document.getElementById("root");

// Sin contenedor no hay dónde montar: error claro en vez de una página en blanco.
if (!raiz) {
  throw new Error("No se encontró el elemento #root en index.html");
}

createRoot(raiz).render(
  <StrictMode>
    <App />
  </StrictMode>,
);