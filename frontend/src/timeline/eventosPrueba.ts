// ---------------------------------------------------------------------------
// eventosPrueba.ts — Utilidades para construir secuencias de eventos en pruebas.
// Genera una historia mínima y válida (seq 1..n) que el reductor aplica sin
// anomalías, con timestamps cada 2 s como la grabación real. No se usa en producción.
// ---------------------------------------------------------------------------
import type { Evento } from "./types.ts";

// Instante base de los timestamps: 2026-11-11T20:00:00-03:00 (= 23:00 UTC).
const BASE_MS = Date.UTC(2026, 10, 11, 23, 0, 0);

// Devuelve el timestamp ISO del evento número `seq` (2 s entre eventos).
export function marcaDeTiempo(seq: number): string {
  return new Date(BASE_MS + (seq - 1) * 2000).toISOString();
}

// Arma un evento con el sobre común; el slide solo se agrega si el evento lo usa.
function crear(
  seq: number,
  runId: string,
  agente: string,
  tipo: string,
  payload: unknown,
  slide?: number,
): Evento {
  const sobre: Record<string, unknown> = {
    version: "0.1",
    run_id: runId,
    seq,
    timestamp: marcaDeTiempo(seq),
    origen: "grabado",
    agente,
    tipo,
    payload,
  };
  // Solo los eventos ligados a un slide llevan el campo `slide`.
  if (slide !== undefined) sobre["slide"] = slide;
  return sobre as unknown as Evento;
}

// Devuelve el evento que le corresponde a cada seq de la historia de prueba.
function eventoDe(seq: number, runId: string): Evento {
  // Los primeros 7 eventos cuentan una mini historia; el resto escribe un título por slide.
  switch (seq) {
    case 1:
      return crear(seq, runId, "sistema", "run_iniciada", {
        entrada_ref: "fuente_prueba.txt",
        plataforma: "instagram",
        idioma_salida: "es",
        num_slides: 3,
        verificacion: "verificada",
        fuente: { tipo: "documento", atribucion: "Texto de prueba", licencia: "Propio" },
      });
    case 2:
      return crear(seq, runId, "sistema", "fuente_indexada", {
        num_fragmentos: 3,
        num_caracteres: 300,
        sha256: "0".repeat(64),
      });
    case 3:
      return crear(seq, runId, "estratega", "brief_emitido", {
        angulo: "Ángulo de prueba",
        tono: "Claro y directo",
        num_slides: 3,
        tipo_mensaje: "lista_de_pasos",
        roles: ["gancho", "desarrollo", "cierre"],
      });
    case 4:
      return crear(seq, runId, "estratega", "plantilla_elegida", {
        plantilla_id: "lista_de_pasos_prueba",
        modo: "auto",
        motivo: "Plantilla de prueba",
        confianza: 0.9,
      });
    case 5:
      return crear(seq, runId, "redactor", "texto_propuesto", { campo: "titulo", texto: "Título 1" }, 1);
    case 6:
      return crear(seq, runId, "director_arte", "colocar_fondo", { fondo: { tipo: "color", valor: "#112233" } }, 1);
    case 7:
      return crear(seq, runId, "director_arte", "escribir_texto", { campo: "titulo", texto: "Título 1" }, 1);
    default: {
      // A partir del seq 8 cada evento escribe el título de un slide nuevo (2, 3, 4...).
      const slide = seq - 6;
      return crear(seq, runId, "director_arte", "escribir_texto", { campo: "titulo", texto: `Título ${slide}` }, slide);
    }
  }
}

// Crea una secuencia limpia de `cantidad` eventos con seq 1..cantidad.
export function crearSecuencia(cantidad: number, runId = "run_prueba"): Evento[] {
  const eventos: Evento[] = [];
  // Un evento por cada seq, de 1 hasta `cantidad`.
  for (let seq = 1; seq <= cantidad; seq++) eventos.push(eventoDe(seq, runId));
  return eventos;
}

// Busca un evento por seq; si no está, la prueba está mal armada y falla con mensaje claro.
export function porSeq(eventos: readonly Evento[], seq: number): Evento {
  const encontrado = eventos.find((e) => e.seq === seq);
  // Un seq ausente es un error de la prueba, no del código bajo prueba.
  if (encontrado === undefined) {
    throw new Error(`La secuencia de prueba no tiene el seq ${seq}.`);
  }
  return encontrado;
}

// Copia del evento con otro seq (para armar duplicados o seq inválidos).
export function conSeq(evento: Evento, seq: number): Evento {
  return { ...evento, seq } as unknown as Evento;
}

// Copia del evento con otro run_id (para armar secuencias mezcladas).
export function conRun(evento: Evento, runId: string): Evento {
  return { ...evento, run_id: runId } as unknown as Evento;
}

// Copia del evento con otro `texto` en el payload (para armar duplicados con contenido distinto).
export function conTexto(evento: Evento, texto: string): Evento {
  return {
    ...evento,
    payload: { ...(evento.payload as object), texto },
  } as unknown as Evento;
}