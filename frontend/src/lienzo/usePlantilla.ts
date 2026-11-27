/**
 * usePlantilla.ts — La plantilla SVG que corresponde al run: la que dice el evento `plantilla_elegida` y, mientras no
 * llega, la plantilla por defecto. Si la pedida no se puede cargar, se informa el error en vez de dibujar con otra.
 */
import { useEffect, useMemo, useState } from "react";
import { aplicarComposicion, aplicarVariante, crearCargadorDePlantillas, ID_PLANTILLA_POR_DEFECTO } from "./cargarPlantilla.ts";

const cargador = crearCargadorDePlantillas();

export interface PlantillaCargada {
  /** Texto del SVG; null mientras se carga la primera o si falló. */
  readonly svg: string | null;
  readonly error: string | null;
}

export function usePlantilla(
  plantillaId: string | undefined,
  reemplazos?: Readonly<Record<string, string>>,
  composicion?: string,
  cargar: (id: string) => Promise<string> = cargador,
): PlantillaCargada {
  const id = plantillaId ?? ID_PLANTILLA_POR_DEFECTO;
  const [carga, setCarga] = useState<{ id: string; svg: string | null; error: string | null }>({ id, svg: null, error: null });

  useEffect(() => {
    let cancelado = false;
    cargar(id).then(
      (svg) => {
        if (!cancelado) setCarga({ id, svg, error: null });
      },
      (e: unknown) => {
        if (!cancelado) setCarga({ id, svg: null, error: e instanceof Error ? e.message : String(e) });
      },
    );
    return () => {
      cancelado = true;
    };
  }, [id, cargar]);

  // Mientras llega la plantilla nueva se sigue mostrando la anterior (evita un parpadeo); un error ajeno no se arrastra.
  // Colores y composición del run solo valen para SU plantilla: no se aplican a la anterior mientras llega la nueva.
  const colores = carga.id === id ? reemplazos : undefined;
  const siluetas = carga.id === id ? composicion : undefined;
  const svg = useMemo(
    () => (carga.svg === null ? null : aplicarVariante(aplicarComposicion(carga.svg, siluetas), colores)),
    [carga.svg, siluetas, colores],
  );
  return { svg, error: carga.id === id ? carga.error : null };
}
