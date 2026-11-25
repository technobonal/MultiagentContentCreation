// ---------------------------------------------------------------------------
// posicionAvatar.ts — Decide qué hace y a dónde va el avatar del agente activo.
// Función pura: solo lee el Estado del reductor y devuelve una descripción
// (agente, acción, destino y burbuja de texto). Quien la dibuja es AvataresVivos.
//
// Cierre del run (9B-3):
//  - Exitoso: el último evento es run_finalizada y la actividad se marca con cierre "exitoso".
//    AvataresVivos muestra «Cerrando la ejecución…» unos segundos y luego deja todo en reposo.
//  - Fallido o cortado (sin run_finalizada): quien llama pasa `runFallido = true` y el avatar del
//    último evento vuelve a reposo con una burbuja de fallo (cierre "fallido").
// ---------------------------------------------------------------------------
import type { Estado } from "../timeline/types.ts";
import { textoFaseDeTipo, ultimoEvento } from "./fase.ts";
import type { IdiomaFase } from "./fase.ts";

// Gesto del avatar: cambia la animación de su herramienta ("reposo" = ninguna).
export type AccionAvatar = "pensar" | "escribir" | "pintar" | "revisar" | "aprobar" | "procesar" | "reposo";

// Dónde trabaja: centro del slide, junto a un campo de texto, esquina (pintar fondo), afirmación subrayada
// o su casilla de reposo (con la burbuja de fallo).
export type DestinoAvatar = "centro" | "campo" | "esquina" | "afirmacion" | "reposo";

// Cómo terminó el run, si la actividad es de cierre: null = actividad normal.
export type CierreAvatar = "exitoso" | "fallido";

// Campo de texto concreto sobre el que se está trabajando.
export interface CampoActivo {
  readonly slide: number;
  readonly campo: string;
}

// Lo que hace el avatar activo en el último evento aplicado.
export interface ActividadAvatar {
  // Cambia con cada evento: reinicia la animación de la burbuja.
  readonly clave: string;
  readonly agente: string;
  readonly accion: AccionAvatar;
  readonly destino: DestinoAvatar;
  readonly burbuja: string;
  // Distinto de null cuando es la actividad de cierre del run (la burbuja dura unos segundos).
  readonly cierre: CierreAvatar | null;
}

// Id de la afirmación verificada por el último evento ("" si no se encuentra).
function idVerificacion(estado: Estado): string {
  // Se busca la entrada del ledger cuya última verificación es este seq.
  for (const [id, registro] of Object.entries(estado.ledger)) {
    if (registro.actual.seq === estado.ultimoSeq) return id;
  }
  return "";
}

// Id del hallazgo abierto por el último evento ("" si no se encuentra).
function idHallazgoAbierto(estado: Estado): string {
  for (const h of Object.values(estado.hallazgos)) {
    // El hallazgo abierto en este seq es el de este evento.
    if (h.abiertoEnSeq === estado.ultimoSeq) return h.hallazgo_id;
  }
  return "";
}

// Id del hallazgo reevaluado por el último evento ("" si no se encuentra).
function idHallazgoReevaluado(estado: Estado): string {
  for (const h of Object.values(estado.hallazgos)) {
    const ultima = h.reevaluaciones[h.reevaluaciones.length - 1];
    // La última reevaluación con este seq pertenece a este evento.
    if (ultima !== undefined && ultima.seq === estado.ultimoSeq) return h.hallazgo_id;
  }
  return "";
}

// Actividad del avatar para el último evento aplicado (null si aún no hay eventos).
// `runFallido` (opcional, false por defecto): el run falló o se cortó sin run_finalizada.
export function actividadDeEstado(
  estado: Estado,
  idioma: IdiomaFase,
  runFallido: boolean = false,
): ActividadAvatar | null {
  const ultimo = ultimoEvento(estado);
  if (ultimo === null) return null;

  const n = estado.slideActivo;
  // Elige el texto según el idioma.
  const f = (es: string, pt: string): string => (idioma === "es" ? es : pt);
  // Datos comunes a toda actividad normal (no es un cierre).
  const base: Pick<ActividadAvatar, "clave" | "agente" | "cierre"> = {
    clave: String(estado.ultimoSeq),
    agente: ultimo.agente,
    cierre: null,
  };

  // Run fallido o cortado: el avatar del último evento vuelve a reposo con una burbuja de fallo.
  // Si el último evento ya es run_finalizada el run sí terminó: manda el cierre exitoso de abajo.
  if (runFallido && ultimo.tipo !== "run_finalizada") {
    return {
      // El sufijo distingue esta burbuja de la del evento normal y reinicia su animación.
      clave: `${estado.ultimoSeq}-fallo`,
      agente: ultimo.agente,
      accion: "reposo",
      destino: "reposo",
      cierre: "fallido",
      burbuja: f("Ejecución interrumpida…", "Execução interrompida…"),
    };
  }

  switch (ultimo.tipo) {
    case "run_iniciada":
      return { ...base, accion: "procesar", destino: "centro", burbuja: f("Iniciando la ejecución…", "Iniciando a execução…") };
    case "fuente_indexada":
      return { ...base, accion: "procesar", destino: "centro", burbuja: f("Indexando la fuente…", "Indexando a fonte…") };
    case "brief_emitido":
      return { ...base, accion: "pensar", destino: "centro", burbuja: f("Planificando el ángulo…", "Planejando o ângulo…") };
    case "plantilla_elegida":
      return { ...base, accion: "pensar", destino: "centro", burbuja: f("Eligiendo plantilla…", "Escolhendo template…") };
    case "texto_propuesto":
      return { ...base, accion: "escribir", destino: "campo", burbuja: f(`Redactando slide ${n}…`, `Redigindo slide ${n}…`) };
    case "colocar_fondo":
      return { ...base, accion: "pintar", destino: "esquina", burbuja: f(`Pintando el fondo del slide ${n}…`, `Pintando o fundo do slide ${n}…`) };
    case "escribir_texto":
      return { ...base, accion: "escribir", destino: "campo", burbuja: f(`Escribiendo slide ${n}…`, `Escrevendo slide ${n}…`) };
    case "verificacion_fidelidad":
      return { ...base, accion: "revisar", destino: "afirmacion", burbuja: `${f("Verificando", "Verificando")} ${idVerificacion(estado)}…` };
    case "hallazgo_abierto":
      return { ...base, accion: "revisar", destino: "afirmacion", burbuja: `${f("Abriendo hallazgo", "Abrindo achado")} ${idHallazgoAbierto(estado)}…` };
    case "hallazgo_corregido":
      return { ...base, accion: "revisar", destino: "afirmacion", burbuja: `${f("Reevaluando", "Reavaliando")} ${idHallazgoReevaluado(estado)}…` };
    case "corregir":
      return { ...base, accion: "escribir", destino: "campo", burbuja: f(`Corrigiendo slide ${n}…`, `Corrigindo slide ${n}…`) };
    case "aprobacion_solicitada":
      return { ...base, accion: "procesar", destino: "centro", burbuja: f("Pidiendo aprobación…", "Pedindo aprovação…") };
    case "aprobada":
      return { ...base, accion: "aprobar", destino: "centro", burbuja: f("Aprobando…", "Aprovando…") };
    case "editada":
      return { ...base, accion: "escribir", destino: "campo", burbuja: f(`Editando slide ${n}…`, `Editando slide ${n}…`) };
    case "run_finalizada":
      // Cierre exitoso: AvataresVivos oculta esta burbuja a los pocos segundos.
      return {
        ...base,
        cierre: "exitoso",
        accion: "procesar",
        destino: "centro",
        burbuja: f("Cerrando la ejecución…", "Encerrando a execução…"),
      };
    default:
      // Tipo desconocido: gesto genérico con la frase de fase.
      return { ...base, accion: "procesar", destino: "centro", burbuja: textoFaseDeTipo(ultimo.tipo, idioma) };
  }
}