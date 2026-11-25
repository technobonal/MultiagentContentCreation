/**
 * MesaAgentes.tsx — Franja con los agentes del sistema: quién acaba de actuar (resaltado
 * y pulsando) y cuál fue la última acción de cada uno. Cada ficha lleva su mini-avatar.
 * Se lee del estado del reductor. Al terminar el run, cada ficha pasa a su estado final
 * ("Terminado" / "Sin intervención") en vez de quedarse con su última acción.
 */
import { Avatar } from "./avatares.tsx";
import { AGENTES_MESA, nombreAgente, textoEstadoAgente, ultimoEvento } from "./fase.ts";
import type { IdiomaFase } from "./fase.ts";
import type { Estado } from "../timeline/types.ts";

export function MesaAgentes({ estado, idioma }: { estado: Estado; idioma: IdiomaFase }) {
  // Agente que hizo el último evento aplicado (null si aún no hay ninguno).
  const activo = ultimoEvento(estado)?.agente ?? null;

  return (
    <div className="mesa" aria-label="Agentes">
      {/* Una ficha por agente, en orden de intervención. */}
      {AGENTES_MESA.map((agente) => {
        const entrada = estado.agentes[agente];
        const clase =
          agente === activo ? "agente agente-activo" : entrada ? "agente agente-hecho" : "agente";
        return (
          <div key={agente} className={clase}>
            <Avatar agente={agente} tamano={22} />
            <div className="agente-texto">
              <span className="agente-nombre">{nombreAgente(agente, idioma)}</span>
              {/* Su última acción mientras el run avanza; su estado final cuando terminó. */}
              <span className="agente-estado">{textoEstadoAgente(estado, agente, idioma)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}