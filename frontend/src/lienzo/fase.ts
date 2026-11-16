// ---------------------------------------------------------------------------
// fase.ts — Etiquetas de fase, nombres de agentes y detalle del paso actual.
// Funciones puras: solo leen el Estado del reductor y devuelven texto en el
// idioma pedido. No tocan el reductor ni el reproductor.
// ---------------------------------------------------------------------------
import type { Estado, Evento } from "../timeline/types.ts";

// Idiomas disponibles para las etiquetas (los mismos que acepta el contrato).
export type IdiomaFase = "es" | "pt-BR";

// Lo que puede elegir el usuario: "auto" = usar el idioma de la guía.
export type EleccionIdioma = "auto" | IdiomaFase;

// Claves internas de fase (varios tipos de evento comparten la misma fase).
type ClaveFase =
  | "inicio"
  | "leyendo"
  | "planificando"
  | "plantilla"
  | "redactando"
  | "disenando"
  | "verificando"
  | "corrigiendo"
  | "aprobacion"
  | "aprobada"
  | "editando"
  | "terminado"
  | "desconocida";

// Texto de cada fase en cada idioma.
const TEXTOS: Readonly<Record<ClaveFase, Readonly<Record<IdiomaFase, string>>>> = {
  inicio: { es: "Listo para reproducir", "pt-BR": "Pronto para reproduzir" },
  leyendo: { es: "Leyendo la fuente…", "pt-BR": "Lendo a fonte…" },
  planificando: { es: "Planificando…", "pt-BR": "Planejando…" },
  plantilla: { es: "Eligiendo plantilla…", "pt-BR": "Escolhendo template…" },
  redactando: { es: "Redactando…", "pt-BR": "Redigindo…" },
  disenando: { es: "Diseñando…", "pt-BR": "Desenhando…" },
  verificando: { es: "Verificando…", "pt-BR": "Verificando…" },
  corrigiendo: { es: "Corrigiendo…", "pt-BR": "Corrigindo…" },
  aprobacion: { es: "Esperando aprobación…", "pt-BR": "Aguardando aprovação…" },
  aprobada: { es: "Aprobada", "pt-BR": "Aprovada" },
  editando: { es: "Editando…", "pt-BR": "Editando…" },
  terminado: { es: "Terminado", "pt-BR": "Concluído" },
  desconocida: { es: "Procesando…", "pt-BR": "Processando…" },
};

// Qué fase corresponde a cada tipo de evento conocido.
const FASE_POR_TIPO: Readonly<Record<string, ClaveFase>> = {
  run_iniciada: "leyendo",
  fuente_indexada: "leyendo",
  brief_emitido: "planificando",
  plantilla_elegida: "plantilla",
  texto_propuesto: "redactando",
  colocar_fondo: "disenando",
  escribir_texto: "disenando",
  verificacion_fidelidad: "verificando",
  hallazgo_abierto: "verificando",
  hallazgo_corregido: "corrigiendo",
  corregir: "corrigiendo",
  aprobacion_solicitada: "aprobacion",
  aprobada: "aprobada",
  editada: "editando",
  run_finalizada: "terminado",
};

// Nombre visible de cada agente en cada idioma.
const NOMBRES_AGENTE: Readonly<Record<string, Readonly<Record<IdiomaFase, string>>>> = {
  estratega: { es: "Estratega", "pt-BR": "Estrategista" },
  redactor: { es: "Redactor", "pt-BR": "Redator" },
  director_arte: { es: "Director de arte", "pt-BR": "Diretor de arte" },
  revisor: { es: "Revisor", "pt-BR": "Revisor" },
  sistema: { es: "Sistema", "pt-BR": "Sistema" },
  humano: { es: "Humano", "pt-BR": "Humano" },
};

// Agentes que se muestran en la mesa de trabajo, en orden de intervención.
export const AGENTES_MESA: readonly string[] = [
  "estratega",
  "redactor",
  "director_arte",
  "revisor",
  "humano",
];

// Último evento aplicado: qué agente lo hizo y de qué tipo era.
export interface UltimoEvento {
  readonly agente: string;
  readonly tipo: string;
}

// Busca en `agentes` la entrada cuyo seq es el último aplicado (null si no hay eventos).
export function ultimoEvento(estado: Estado): UltimoEvento | null {
  if (estado.ultimoSeq === 0) return null;
  // Solo una entrada puede coincidir: cada seq pertenece a un único evento.
  for (const [agente, entrada] of Object.entries(estado.agentes)) {
    if (entrada.seq === estado.ultimoSeq) return { agente, tipo: entrada.tipo };
  }
  return null;
}

// Frase de fase para un tipo de evento (tipos desconocidos caen en "Procesando…").
export function textoFaseDeTipo(tipo: string, idioma: IdiomaFase): string {
  const clave: ClaveFase = FASE_POR_TIPO[tipo] ?? "desconocida";
  return TEXTOS[clave][idioma];
}

// Etiqueta de fase para el estado actual y el idioma pedido.
export function faseDeEstado(estado: Estado, idioma: IdiomaFase): string {
  // Sin eventos aplicados todavía: el reproductor está en el evento 0.
  if (estado.ultimoSeq === 0) return TEXTOS.inicio[idioma];
  const ultimo = ultimoEvento(estado);
  // Si no se encuentra el último evento se usa la fase genérica.
  if (ultimo === null) return TEXTOS.desconocida[idioma];
  return textoFaseDeTipo(ultimo.tipo, idioma);
}

// Nombre visible de un agente (si es desconocido, se devuelve la clave tal cual).
export function nombreAgente(agente: string, idioma: IdiomaFase): string {
  return NOMBRES_AGENTE[agente]?.[idioma] ?? agente;
}

// Texto de un agente que todavía no intervino.
export function textoEspera(idioma: IdiomaFase): string {
  return idioma === "es" ? "En espera" : "Em espera";
}

// Detalle del paso actual (solo para los pasos del estratega y del sistema); null si no hay.
export function detalleDeFase(estado: Estado, idioma: IdiomaFase): string | null {
  const ultimo = ultimoEvento(estado);
  if (ultimo === null) return null;

  switch (ultimo.tipo) {
    case "run_iniciada": {
      const r = estado.run;
      if (r === null) return null;
      return `${r.plataforma} · ${r.num_slides} slides · ${r.idioma_salida}`;
    }
    case "fuente_indexada": {
      const f = estado.fuente;
      if (f === null) return null;
      const trozos = idioma === "es" ? "fragmentos" : "trechos";
      return `${f.num_fragmentos} ${trozos} · ${f.num_caracteres} caracteres`;
    }
    case "brief_emitido": {
      const b = estado.brief;
      return b === null ? null : b.angulo;
    }
    case "plantilla_elegida": {
      const p = estado.plantilla;
      if (p === null) return null;
      return `${p.motivo} · ${Math.round(p.confianza * 100)} %`;
    }
    default:
      return null;
  }
}

// Idioma de la guía: sale del evento run_iniciada (campo idioma_salida); por defecto español.
export function idiomaDeGuia(eventos: readonly Evento[]): IdiomaFase {
  // Se busca el primer run_iniciada de la lista.
  for (const evento of eventos) {
    // El chequeo de tipo estrecha el payload a PayloadRunIniciada.
    if (evento.tipo === "run_iniciada") {
      return evento.payload.idioma_salida === "pt-BR" ? "pt-BR" : "es";
    }
  }
  return "es";
}

// Convierte el valor crudo de un <select> en una elección válida ("auto" si no reconoce).
export function leerEleccion(valor: string): EleccionIdioma {
  return valor === "es" || valor === "pt-BR" ? valor : "auto";
}