/**
 * useReproductor.ts — Conecta un Reproductor con React sin copiar su estado:
 * useSyncExternalStore lee la vista actual y se suscribe a sus cambios.
 */
import { useCallback, useSyncExternalStore } from "react";
import type { Reproductor, VistaReproductor } from "../timeline/reproductor.ts";

/** Devuelve la vista actual del reproductor y vuelve a renderizar cuando cambia. */
export function useReproductor(reproductor: Reproductor): VistaReproductor {
  // Funciones estables mientras el reproductor sea el mismo (React las compara por referencia).
  const suscribir = useCallback(
    (aviso: () => void) => reproductor.suscribir(() => aviso()),
    [reproductor],
  );
  const obtener = useCallback(() => reproductor.obtener(), [reproductor]);

  return useSyncExternalStore(suscribir, obtener);
}