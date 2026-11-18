/**
 * useEnVivo.ts — Conecta el estado de la conexión de una FuenteEnVivo con React.
 * Igual que useReproductor: useSyncExternalStore lee la vista actual sin copiarla.
 */
import { useCallback, useSyncExternalStore } from "react";
import type { FuenteEnVivo, VistaEnVivo } from "../timeline/fuenteEnVivo.ts";

/** Devuelve la conexión, el buffer de eventos y el mensaje; re-renderiza cuando cambian. */
export function useEnVivo(fuente: FuenteEnVivo): VistaEnVivo {
  // Funciones estables mientras la fuente sea la misma (React las compara por referencia).
  const suscribir = useCallback(
    (aviso: () => void) => fuente.suscribir(() => aviso()),
    [fuente],
  );
  const obtener = useCallback(() => fuente.obtenerEnVivo(), [fuente]);

  return useSyncExternalStore(suscribir, obtener);
}