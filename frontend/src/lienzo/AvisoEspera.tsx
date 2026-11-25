/**
 * AvisoEspera.tsx — Aviso «esperando al servidor» cuando un run en vivo lleva unos segundos sin eventos.
 * Cuenta el silencio desde el último `seq` recibido; cualquier evento nuevo reinicia la cuenta.
 */
import { useEffect, useState } from "react";
import type { Estado } from "../timeline/types.ts";
import { puedeEstarEsperando, textoEspera } from "./espera.ts";

export function AvisoEspera({ estado }: { estado: Estado }) {
  const activo = puedeEstarEsperando(estado);
  const [segundos, setSegundos] = useState(0);

  useEffect(() => {
    setSegundos(0);
    if (!activo) return;
    const desde = Date.now();
    const id = setInterval(() => setSegundos((Date.now() - desde) / 1000), 1000);
    return () => clearInterval(id);
  }, [activo, estado.ultimoSeq]);

  const texto = activo ? textoEspera(segundos) : null;
  if (texto === null) return null;
  return (
    <p className="aviso-espera" role="status">
      {texto}
    </p>
  );
}
