// ---------------------------------------------------------------------------
// revisor.ts — Tarjeta del revisor: qué mostrar cuando el último evento fue una
// verificación, un hallazgo, su corrección o la aprobación. Todo sale del Estado
// (puro, sin DOM), así que también funciona al mover el slider.
// ---------------------------------------------------------------------------
import type { Estado, Gravedad, Veredicto } from "../timeline/types.ts";
import { ultimoEvento } from "./fase.ts";
import type { IdiomaFase } from "./fase.ts";

// Color semántico de la tarjeta y del subrayado.
export type TonoTarjeta = "error" | "aviso" | "ok";

// Cita o evidencia que acompaña a la tarjeta.
export interface CitaTarjeta {
  readonly etiqueta: string;
  readonly texto: string;
}

// Datos listos para dibujar la tarjeta.
export interface TarjetaRevisor {
  // Cambia con cada evento: sirve para reiniciar la animación.
  readonly clave: string;
  readonly tono: TonoTarjeta;
  readonly titulo: string;
  readonly lineas: readonly string[];
  readonly cita: CitaTarjeta | null;
  // Slide donde subrayar y texto a subrayar (null si no aplica).
  readonly slide: number | null;
  readonly afirmacion: string | null;
}

type Textos = Readonly<Record<IdiomaFase, string>>;

// Etiqueta del veredicto en cada idioma.
const VEREDICTOS: Readonly<Record<Veredicto, Textos>> = {
  respaldada: { es: "Respaldada", "pt-BR": "Respaldada" },
  parcialmente_respaldada: { es: "Parcialmente respaldada", "pt-BR": "Parcialmente respaldada" },
  no_respaldada: { es: "No respaldada", "pt-BR": "Não respaldada" },
  contradice: { es: "Contradice la fuente", "pt-BR": "Contradiz a fonte" },
  no_verificada: { es: "No verificada", "pt-BR": "Não verificada" },
  no_aplica: { es: "No aplica", "pt-BR": "Não se aplica" },
};

// Color según el veredicto.
const TONO_VEREDICTO: Readonly<Record<Veredicto, TonoTarjeta>> = {
  respaldada: "ok",
  parcialmente_respaldada: "aviso",
  no_respaldada: "error",
  contradice: "error",
  no_verificada: "aviso",
  no_aplica: "ok",
};

// Gravedad de un hallazgo en cada idioma, y su color.
const GRAVEDADES: Readonly<Record<Gravedad, Textos>> = {
  bloqueante: { es: "bloqueante", "pt-BR": "bloqueante" },
  mayor: { es: "mayor", "pt-BR": "maior" },
  menor: { es: "menor", "pt-BR": "menor" },
};
const TONO_GRAVEDAD: Readonly<Record<Gravedad, TonoTarjeta>> = {
  bloqueante: "error",
  mayor: "aviso",
  menor: "aviso",
};

// Textos sueltos de la tarjeta.
const T = {
  fuente: { es: "Fuente", "pt-BR": "Fonte" },
  evidencia: { es: "Evidencia", "pt-BR": "Evidência" },
  verificacion: { es: "Verificación", "pt-BR": "Verificação" },
  hallazgo: { es: "Hallazgo", "pt-BR": "Achado" },
  corregido: { es: "Hallazgo corregido", "pt-BR": "Achado corrigido" },
  persiste: { es: "El hallazgo persiste", "pt-BR": "O achado persiste" },
  esperando: { es: "Esperando aprobación humana", "pt-BR": "Aguardando aprovação humana" },
  aprobadaHumano: { es: "Aprobada por el humano", "pt-BR": "Aprovada pelo humano" },
  sinVistoBueno: { es: "Aprobada por una persona, sin visto bueno", "pt-BR": "Aprovada por uma pessoa, sem aval" },
  rechazadaHumano: { es: "Rechazada por el humano", "pt-BR": "Rejeitada pelo humano" },
  respaldadas: { es: "afirmaciones respaldadas", "pt-BR": "afirmações respaldadas" },
  abiertos: { es: "hallazgos abiertos", "pt-BR": "achados abertos" },
} as const satisfies Record<string, Textos>;

// Busca una afirmación dentro de un texto; devuelve el rango [inicio, fin) o null.
// Ignora mayúsculas y la puntuación final de la afirmación ("…30 minutos." -> "…30 minutos").
export function localizarAfirmacion(
  texto: string,
  afirmacion: string,
): { readonly inicio: number; readonly fin: number } | null {
  const limpia = afirmacion.trim().replace(/[.!?…]+$/u, "").trim();
  // Una afirmación vacía no se puede ubicar.
  if (limpia === "") return null;
  const inicio = texto.toLowerCase().indexOf(limpia.toLowerCase());
  // No aparece literalmente en el texto: no se subraya nada.
  if (inicio < 0) return null;
  return { inicio, fin: inicio + limpia.length };
}

// Arma la tarjeta del último evento aplicado, o null si ese evento no es del revisor/humano.
export function tarjetaDeRevisor(estado: Estado, idioma: IdiomaFase): TarjetaRevisor | null {
  const ultimo = ultimoEvento(estado);
  if (ultimo === null) return null;
  const clave = String(estado.ultimoSeq);

  // Verificación de fidelidad: la entrada del ledger escrita por este evento.
  if (ultimo.tipo === "verificacion_fidelidad") {
    // Se busca la entrada cuya última verificación es este seq.
    for (const registro of Object.values(estado.ledger)) {
      const e = registro.actual;
      if (e.seq !== estado.ultimoSeq) continue;
      return {
        clave,
        tono: TONO_VEREDICTO[e.veredicto],
        titulo: `${T.verificacion[idioma]} · ${VEREDICTOS[e.veredicto][idioma]}`,
        lineas: [`«${e.afirmacion}»`, e.motivo],
        cita: e.cita === null ? null : { etiqueta: T.fuente[idioma], texto: e.cita.fragmento },
        slide: e.slide,
        afirmacion: e.afirmacion,
      };
    }
    return null;
  }

  // Hallazgo abierto: el hallazgo cuyo abiertoEnSeq es este seq.
  if (ultimo.tipo === "hallazgo_abierto") {
    for (const h of Object.values(estado.hallazgos)) {
      if (h.abiertoEnSeq !== estado.ultimoSeq) continue;
      return {
        clave,
        tono: TONO_GRAVEDAD[h.gravedad],
        titulo: `${T.hallazgo[idioma]} · ${GRAVEDADES[h.gravedad][idioma]}`,
        lineas: [h.explicacion, `→ ${h.accion}`],
        cita: { etiqueta: T.evidencia[idioma], texto: h.evidencia },
        slide: h.slide,
        // Si la evidencia está literal en el slide, se subraya.
        afirmacion: h.evidencia,
      };
    }
    return null;
  }

  // Hallazgo corregido (o que persiste): la reevaluación escrita por este evento.
  if (ultimo.tipo === "hallazgo_corregido") {
    for (const h of Object.values(estado.hallazgos)) {
      const reeval = h.reevaluaciones[h.reevaluaciones.length - 1];
      if (reeval === undefined || reeval.seq !== estado.ultimoSeq) continue;
      const corregido = reeval.resultado === "corregido";
      return {
        clave,
        tono: corregido ? "ok" : "error",
        titulo: corregido ? T.corregido[idioma] : T.persiste[idioma],
        lineas: [reeval.texto],
        cita: null,
        slide: h.slide,
        afirmacion: null,
      };
    }
    return null;
  }

  // Aprobación solicitada: resumen del sello y de los hallazgos abiertos.
  if (ultimo.tipo === "aprobacion_solicitada") {
    const r = estado.revision;
    if (r === null) return null;
    const s = r.sello;
    return {
      clave,
      tono: r.estado_revision === "aprobada" ? "ok" : "aviso",
      titulo: T.esperando[idioma],
      lineas: [
        `${s.afirmaciones_respaldadas}/${s.afirmaciones_totales} ${T.respaldadas[idioma]} · ${r.hallazgos_abiertos} ${T.abiertos[idioma]}`,
      ],
      cita: null,
      slide: null,
      afirmacion: null,
    };
  }

  // Rechazo del humano: su motivo y, si lo dio, qué se esperaba.
  if (ultimo.tipo === "rechazada") {
    const rechazo = estado.decision?.rechazo;
    if (rechazo === undefined) return null;
    return {
      clave,
      tono: "aviso",
      titulo: T.rechazadaHumano[idioma],
      lineas: rechazo.esperado === undefined ? [rechazo.motivo] : [rechazo.motivo, rechazo.esperado],
      cita: null,
      slide: null,
      afirmacion: null,
    };
  }

  // Aprobación del humano (con su comentario si lo hay).
  if (ultimo.tipo === "aprobada") {
    const d = estado.decision;
    if (d === null) return null;
    return {
      clave,
      tono: d.excepcion === undefined ? "ok" : "aviso",
      titulo: (d.excepcion === undefined ? T.aprobadaHumano : T.sinVistoBueno)[idioma],
      lineas: [d.excepcion?.motivo, d.comentario].filter((l): l is string => l !== undefined),
      cita: null,
      slide: null,
      afirmacion: null,
    };
  }

  return null;
}