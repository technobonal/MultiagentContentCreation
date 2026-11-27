// ---------------------------------------------------------------------------
// types.ts — Tipos del contrato de eventos 0.1 y del estado del reductor.
// Reflejan contracts/common.schema.json y contracts/events/*.schema.json.
// Sin `enum` (erasableSyntaxOnly): se usan objetos `as const` y uniones literales.
// ---------------------------------------------------------------------------

// Catálogo de tipos de evento (mismo orden que el enum de envelope.schema.json).
export const TIPOS_EVENTO = [
  "run_iniciada",
  "fuente_indexada",
  "brief_emitido",
  "plantilla_elegida",
  "texto_propuesto",
  "colocar_fondo",
  "colocar_imagen",
  "escribir_texto",
  "verificacion_fidelidad",
  "hallazgo_abierto",
  "hallazgo_corregido",
  "corregir",
  "aprobacion_solicitada",
  "aprobada",
  "rechazada",
  "editada",
  "run_finalizada",
] as const;

export type TipoEvento = (typeof TIPOS_EVENTO)[number];

// --- Tipos comunes (common.schema.json) ------------------------------------
export type Agente =
  | "estratega"
  | "redactor"
  | "director_arte"
  | "revisor"
  | "sistema"
  | "humano";
export type Origen = "real" | "grabado";
export type Idioma = "es" | "pt-BR";
export type Modo = "auto" | "fijo";
export type TipoMensaje = "lista_de_pasos" | "antes_despues" | "comparativa";
export type RolSlide =
  | "gancho"
  | "segundo_gancho"
  | "desarrollo"
  | "cierre"
  | "fuentes";
export type Veredicto =
  | "respaldada"
  | "parcialmente_respaldada"
  | "no_respaldada"
  | "contradice"
  | "no_verificada"
  | "no_aplica";
export type Gravedad = "bloqueante" | "mayor" | "menor";
export type Dimension =
  | "fidelidad"
  | "especificaciones_red"
  | "atribucion_licencia"
  | "claridad"
  | "gancho"
  | "gancho_slide2"
  | "valor_guardable"
  | "estructura"
  | "contraste"
  | "desbordes"
  | "zona_segura"
  | "idioma"
  | "longitud"
  | "marca"
  | "variedad";
export type EstadoRevision =
  | "aprobada"
  | "aprobada_con_advertencias"
  | "requiere_humano";

// Sello "N de M afirmaciones respaldadas".
export interface Sello {
  readonly afirmaciones_respaldadas: number;
  readonly afirmaciones_totales: number;
}

// Fragmento literal de la fuente con su posición.
export interface Cita {
  readonly fragmento: string;
  readonly inicio: number;
  readonly fin: number;
}

// Fondo de un slide: color sólido o imagen con licencia.
export type Fondo =
  | { readonly tipo: "color"; readonly valor: string }
  | {
      readonly tipo: "imagen";
      readonly referencia: string;
      readonly licencia: string;
    };

// --- Payloads (uno por tipo de evento) -------------------------------------
export interface PayloadRunIniciada {
  readonly entrada_ref: string;
  readonly plataforma: "instagram";
  readonly idioma_salida: Idioma;
  readonly num_slides: number;
  readonly verificacion: "verificada" | "sin_fuente_verificada";
  readonly fuente: {
    readonly tipo: "documento" | "url" | "tema";
    readonly atribucion: string;
    readonly licencia: string;
  };
}
export interface PayloadFuenteIndexada {
  readonly num_fragmentos: number;
  readonly num_caracteres: number;
  readonly sha256: string;
}
export interface PayloadBriefEmitido {
  readonly angulo: string;
  readonly tono: string;
  readonly num_slides: number;
  readonly tipo_mensaje: TipoMensaje;
  readonly roles: readonly RolSlide[];
}
export interface PayloadPlantillaElegida {
  readonly plantilla_id: string;
  /** Composición (siluetas y adornos), si la plantilla declara composiciones. */
  readonly composicion?: string;
  /** Variante de color, si la plantilla declara variantes. */
  readonly variante?: { readonly id: string; readonly reemplazos: Readonly<Record<string, string>> };
  readonly modo: Modo;
  readonly motivo: string;
  readonly confianza: number;
}
export interface PayloadTextoCampo {
  // Sirve para texto_propuesto y escribir_texto (misma forma).
  readonly campo: string;
  readonly texto: string;
}
export interface PayloadColocarFondo {
  readonly fondo: Fondo;
}
// Imagen en un campo de imagen de la plantilla (no el fondo del slide). La sirve el backend por `referencia`.
export interface PayloadColocarImagen {
  readonly campo: string;
  readonly referencia: string;
  readonly licencia: string;
  readonly texto_alternativo: string;
}
export type ImagenColocada = Omit<PayloadColocarImagen, "campo">;
export interface PayloadVerificacionFidelidad {
  readonly afirmacion_id: string;
  readonly afirmacion: string;
  readonly clasificacion: "factual" | "opinion_cta";
  readonly veredicto: Veredicto;
  readonly cita: Cita | null;
  readonly motivo: string;
}
export interface PayloadHallazgoAbierto {
  readonly hallazgo_id: string;
  readonly dimension: Dimension;
  readonly gravedad: Gravedad;
  readonly evidencia: string;
  readonly explicacion: string;
  readonly accion: string;
  readonly responsable: "redactor" | "director_arte" | "estratega";
}
export interface PayloadHallazgoCorregido {
  readonly hallazgo_id: string;
  readonly resultado: "corregido" | "persiste";
  readonly reevaluacion: string;
}
export interface PayloadCorregir {
  readonly motivo: string;
  readonly operacion_nueva: {
    readonly tipo: "escribir_texto";
    readonly campo: string;
    readonly texto: string;
  };
}
export interface PayloadAprobacionSolicitada {
  readonly estado_revision: EstadoRevision;
  readonly hallazgos_abiertos: number;
  readonly sello: Sello;
}
export interface PayloadAprobada {
  readonly decision: "aprobada";
  readonly comentario?: string;
}
export interface PayloadRechazada {
  readonly decision: "rechazada";
  readonly motivo: string;
  readonly responsable?: "estratega" | "redactor" | "director_arte" | "revisor";
  readonly esperado?: string;
}
export interface PayloadEditada {
  readonly campo: string;
  readonly texto_antes: string;
  readonly texto_despues: string;
}
export interface PayloadRunFinalizada {
  /** "rechazada" solo si la persona rechazó el pack. */
  readonly estado_final: EstadoRevision | "rechazada";
  readonly fact_ledger_ref: string;
  readonly sello: Sello;
}

// --- Sobre del evento (envelope.schema.json) -------------------------------
// `slide` y `causa` son opcionales en el sobre; cada tipo exige los suyos en el esquema.
interface Sobre<T extends TipoEvento, P> {
  readonly version: string;
  readonly run_id: string;
  readonly seq: number;
  readonly timestamp: string;
  readonly origen: Origen;
  readonly agente: Agente;
  readonly tipo: T;
  readonly slide?: number;
  readonly causa?: number;
  readonly payload: P;
}

// Unión discriminada por `tipo`: el compilador estrecha el payload en cada `case`.
export type Evento =
  | Sobre<"run_iniciada", PayloadRunIniciada>
  | Sobre<"fuente_indexada", PayloadFuenteIndexada>
  | Sobre<"brief_emitido", PayloadBriefEmitido>
  | Sobre<"plantilla_elegida", PayloadPlantillaElegida>
  | Sobre<"texto_propuesto", PayloadTextoCampo>
  | Sobre<"colocar_fondo", PayloadColocarFondo>
  | Sobre<"colocar_imagen", PayloadColocarImagen>
  | Sobre<"escribir_texto", PayloadTextoCampo>
  | Sobre<"verificacion_fidelidad", PayloadVerificacionFidelidad>
  | Sobre<"hallazgo_abierto", PayloadHallazgoAbierto>
  | Sobre<"hallazgo_corregido", PayloadHallazgoCorregido>
  | Sobre<"corregir", PayloadCorregir>
  | Sobre<"aprobacion_solicitada", PayloadAprobacionSolicitada>
  | Sobre<"aprobada", PayloadAprobada>
  | Sobre<"rechazada", PayloadRechazada>
  | Sobre<"editada", PayloadEditada>
  | Sobre<"run_finalizada", PayloadRunFinalizada>;

// --- Anomalías --------------------------------------------------------------
export type CodigoAnomalia =
  | "run_distinto"
  | "tipo_desconocido"
  | "slide_ausente"
  | "editada_texto_antes_distinto"
  | "editada_sin_cambio"
  | "sello_distinto"
  | "hallazgos_abiertos_distinto"
  | "hallazgo_corregido_sin_hallazgo"
  | "aprobada_con_bloqueante_abierto"
  | "fondo_imagen_sin_licencia";

export interface Anomalia {
  readonly seq: number; // seq del evento que la provocó
  readonly codigo: CodigoAnomalia;
  readonly detalle: string;
}

// --- Estado del reductor ----------------------------------------------------
export interface Hueco {
  readonly esperado: number;
  readonly recibido: number;
}

// Entrada del ledger por afirmacion_id: la última verificación gana, el resto es historial.
export interface EntradaLedger {
  readonly seq: number;
  readonly slide: number | null;
  readonly afirmacion: string;
  readonly clasificacion: "factual" | "opinion_cta";
  readonly veredicto: Veredicto;
  readonly cita: Cita | null;
  readonly motivo: string;
}
export interface RegistroLedger {
  readonly actual: EntradaLedger;
  readonly historial: readonly EntradaLedger[]; // incluye la actual, en orden de seq
}

export interface Reevaluacion {
  readonly seq: number;
  readonly resultado: "corregido" | "persiste";
  readonly texto: string;
}
export interface Hallazgo {
  readonly hallazgo_id: string;
  readonly estado: "abierto" | "corregido";
  readonly slide: number | null;
  readonly abiertoEnSeq: number;
  readonly dimension: Dimension;
  readonly gravedad: Gravedad;
  readonly evidencia: string;
  readonly explicacion: string;
  readonly accion: string;
  readonly responsable: "redactor" | "director_arte" | "estratega";
  readonly reevaluaciones: readonly Reevaluacion[];
}

export interface Edicion {
  readonly seq: number;
  readonly slide: number | null;
  readonly campo: string;
  readonly texto_antes: string;
  readonly texto_despues: string;
}

// Mapa slide -> campo -> valor (usado por propuestas y por los textos dibujados).
export type TextosPorSlide = Readonly<
  Record<number, Readonly<Record<string, string>>>
>;

export interface Estado {
  readonly ultimoSeq: number;
  readonly hueco: Hueco | null;
  readonly runId: string | null;
  readonly origenes: readonly Origen[];
  readonly run: PayloadRunIniciada | null;
  readonly fuente: PayloadFuenteIndexada | null;
  readonly brief: PayloadBriefEmitido | null;
  readonly plantilla: PayloadPlantillaElegida | null;
  // Capa borrador (redactor): lo que se propuso pero aún no se dibuja.
  readonly propuestas: TextosPorSlide;
  // Capa dibujada: lo único que pinta el lienzo.
  readonly lienzo: {
    readonly fondos: Readonly<Record<number, Fondo>>;
    readonly textos: TextosPorSlide;
    // Imágenes dibujadas: por slide y por campo de imagen de la plantilla.
    readonly imagenes: Readonly<Record<number, Readonly<Record<string, ImagenColocada>>>>;
  };
  readonly ledger: Readonly<Record<string, RegistroLedger>>;
  readonly hallazgos: Readonly<Record<string, Hallazgo>>;
  readonly revision: PayloadAprobacionSolicitada | null;
  // La decisión humana: una aprobación (con su comentario) o, si trae `rechazo`, un rechazo.
  readonly decision: {
    readonly seq: number;
    readonly comentario?: string;
    readonly rechazo?: PayloadRechazada & { readonly slide?: number };
  } | null;
  readonly final: PayloadRunFinalizada | null;
  readonly ediciones: readonly Edicion[];
  readonly agentes: Readonly<Record<string, { readonly tipo: string; readonly seq: number }>>;
  readonly slideActivo: number;
  readonly anomalias: readonly Anomalia[];
}