// ---------------------------------------------------------------------------
// reducer.ts — Reductor puro e inmutable: (estado, evento) -> estado nuevo.
// Reglas: idempotente por seq, estricto (seq = ultimoSeq + 1), tolerante a tipos
// desconocidos, nunca muta la entrada y no conoce la plantilla.
// ---------------------------------------------------------------------------
import type {
  Anomalia,
  CodigoAnomalia,
  Estado,
  Evento,
  Fondo,
  Hallazgo,
  Origen,
  RegistroLedger,
  Sello,
  TextosPorSlide,
} from "./types.ts";

// Parche parcial del estado + anomalías (sin seq: lo pone el compositor).
interface Resultado {
  readonly parche: Partial<Estado>;
  readonly anomalias: readonly { codigo: CodigoAnomalia; detalle: string }[];
}

// Crea el estado vacío del que parte toda ejecución.
export function crearEstadoInicial(): Estado {
  return {
    ultimoSeq: 0,
    hueco: null,
    runId: null,
    origenes: [],
    run: null,
    fuente: null,
    brief: null,
    plantilla: null,
    propuestas: {},
    lienzo: { fondos: {}, textos: {}, imagenes: {} },
    ledger: {},
    hallazgos: {},
    revision: null,
    decision: null,
    final: null,
    asesor: null,
    ediciones: [],
    agentes: {},
    slideActivo: 1,
    anomalias: [],
  };
}

// Calcula el sello desde el ledger: cuenta afirmaciones factuales distintas.
// Supuesto: `no_verificada` cuenta en el total pero no como respaldada;
// `opinion_cta` queda fuera.
export function calcularSello(ledger: Estado["ledger"]): Sello {
  let respaldadas = 0;
  let totales = 0;
  for (const registro of Object.values(ledger)) {
    // Las opiniones/CTA no son verificables: no entran al sello.
    if (registro.actual.clasificacion !== "factual") continue;
    totales += 1;
    // Solo el último veredicto "respaldada" suma.
    if (registro.actual.veredicto === "respaldada") respaldadas += 1;
  }
  return { afirmaciones_respaldadas: respaldadas, afirmaciones_totales: totales };
}

// Cuenta los hallazgos que siguen abiertos.
export function contarHallazgosAbiertos(hallazgos: Estado["hallazgos"]): number {
  let abiertos = 0;
  for (const h of Object.values(hallazgos)) {
    // Un hallazgo "persiste" sigue en estado abierto.
    if (h.estado === "abierto") abiertos += 1;
  }
  return abiertos;
}

// Devuelve true si hay algún hallazgo bloqueante abierto.
function hayBloqueanteAbierto(hallazgos: Estado["hallazgos"]): boolean {
  return Object.values(hallazgos).some(
    (h) => h.estado === "abierto" && h.gravedad === "bloqueante",
  );
}

// Compara dos sellos por valor.
function mismoSello(a: Sello, b: Sello): boolean {
  return (
    a.afirmaciones_respaldadas === b.afirmaciones_respaldadas &&
    a.afirmaciones_totales === b.afirmaciones_totales
  );
}

// Devuelve un mapa slide->campo->valor con un campo cambiado (estructura compartida).
function conCampo(
  mapa: TextosPorSlide,
  slide: number,
  campo: string,
  valor: string,
): TextosPorSlide {
  return { ...mapa, [slide]: { ...(mapa[slide] ?? {}), [campo]: valor } };
}

// Atajo para construir un Resultado.
function resultado(
  parche: Partial<Estado>,
  anomalias: Resultado["anomalias"] = [],
): Resultado {
  return { parche, anomalias };
}

// Resultado de un evento que necesita slide pero no lo trae.
function sinSlide(tipo: string): Resultado {
  return resultado({}, [
    { codigo: "slide_ausente", detalle: `El evento ${tipo} no trae slide.` },
  ]);
}

// Aplica el efecto propio de cada tipo sobre el estado ya actualizado con los metadatos.
function aplicarTipo(estado: Estado, evento: Evento): Resultado {
  switch (evento.tipo) {
    case "run_iniciada":
      return resultado({ run: evento.payload });

    case "fuente_indexada":
      return resultado({ fuente: evento.payload });

    case "brief_emitido":
      return resultado({ brief: evento.payload });

    case "plantilla_elegida":
      return resultado({ plantilla: evento.payload });

    case "texto_propuesto": {
      // Capa borrador: no toca el lienzo.
      if (evento.slide === undefined) return sinSlide(evento.tipo);
      const { campo, texto } = evento.payload;
      return resultado({
        propuestas: conCampo(estado.propuestas, evento.slide, campo, texto),
      });
    }

    case "colocar_imagen": {
      if (evento.slide === undefined) return sinSlide(evento.tipo);
      const { campo, ...imagen } = evento.payload;
      return resultado({
        lienzo: {
          ...estado.lienzo,
          imagenes: {
            ...estado.lienzo.imagenes,
            [evento.slide]: { ...estado.lienzo.imagenes[evento.slide], [campo]: imagen },
          },
        },
      });
    }

    case "colocar_fondo": {
      if (evento.slide === undefined) return sinSlide(evento.tipo);
      const fondo: Fondo = evento.payload.fondo;
      const anomalias: { codigo: CodigoAnomalia; detalle: string }[] = [];
      // Defensa: el esquema ya lo impide, pero el reductor no lo asume.
      if (fondo.tipo === "imagen" && !fondo.licencia) {
        anomalias.push({
          codigo: "fondo_imagen_sin_licencia",
          detalle: `Fondo de imagen sin licencia en el slide ${evento.slide}.`,
        });
      }
      return resultado(
        {
          lienzo: {
            ...estado.lienzo,
            fondos: { ...estado.lienzo.fondos, [evento.slide]: fondo },
          },
        },
        anomalias,
      );
    }

    case "escribir_texto": {
      if (evento.slide === undefined) return sinSlide(evento.tipo);
      const { campo, texto } = evento.payload;
      return resultado({
        lienzo: {
          ...estado.lienzo,
          textos: conCampo(estado.lienzo.textos, evento.slide, campo, texto),
        },
      });
    }

    case "verificacion_fidelidad": {
      const p = evento.payload;
      const entrada = {
        seq: evento.seq,
        slide: evento.slide ?? null,
        afirmacion: p.afirmacion,
        clasificacion: p.clasificacion,
        veredicto: p.veredicto,
        cita: p.cita,
        motivo: p.motivo,
      };
      const previo = estado.ledger[p.afirmacion_id];
      // La última verificación gana; el historial conserva todas como evidencia.
      const registro: RegistroLedger = {
        actual: entrada,
        historial: [...(previo?.historial ?? []), entrada],
      };
      return resultado({ ledger: { ...estado.ledger, [p.afirmacion_id]: registro } });
    }

    case "hallazgo_abierto": {
      const p = evento.payload;
      const hallazgo: Hallazgo = {
        hallazgo_id: p.hallazgo_id,
        estado: "abierto",
        slide: evento.slide ?? null,
        abiertoEnSeq: evento.seq,
        dimension: p.dimension,
        gravedad: p.gravedad,
        evidencia: p.evidencia,
        explicacion: p.explicacion,
        accion: p.accion,
        responsable: p.responsable,
        reevaluaciones: [],
      };
      return resultado({ hallazgos: { ...estado.hallazgos, [p.hallazgo_id]: hallazgo } });
    }

    case "hallazgo_corregido": {
      const p = evento.payload;
      const previo = estado.hallazgos[p.hallazgo_id];
      // Sin hallazgo previo no hay nada que cerrar: se registra la anomalía.
      if (!previo) {
        return resultado({}, [
          {
            codigo: "hallazgo_corregido_sin_hallazgo",
            detalle: `No existe un hallazgo abierto con id ${p.hallazgo_id}.`,
          },
        ]);
      }
      const actualizado: Hallazgo = {
        ...previo,
        // Solo "corregido" cierra; "persiste" lo mantiene abierto.
        estado: p.resultado === "corregido" ? "corregido" : "abierto",
        reevaluaciones: [
          ...previo.reevaluaciones,
          { seq: evento.seq, resultado: p.resultado, texto: p.reevaluacion },
        ],
      };
      return resultado({ hallazgos: { ...estado.hallazgos, [p.hallazgo_id]: actualizado } });
    }

    case "corregir": {
      // Reemplaza lo dibujado y deja las propuestas tal cual.
      if (evento.slide === undefined) return sinSlide(evento.tipo);
      const { campo, texto } = evento.payload.operacion_nueva;
      return resultado({
        lienzo: {
          ...estado.lienzo,
          textos: conCampo(estado.lienzo.textos, evento.slide, campo, texto),
        },
      });
    }

    case "aprobacion_solicitada": {
      const p = evento.payload;
      const anomalias: { codigo: CodigoAnomalia; detalle: string }[] = [];
      const calculado = calcularSello(estado.ledger);
      // El sello del evento debe coincidir con el calculado por código.
      if (!mismoSello(p.sello, calculado)) {
        anomalias.push({
          codigo: "sello_distinto",
          detalle: `Evento ${p.sello.afirmaciones_respaldadas}/${p.sello.afirmaciones_totales}, calculado ${calculado.afirmaciones_respaldadas}/${calculado.afirmaciones_totales}.`,
        });
      }
      const abiertos = contarHallazgosAbiertos(estado.hallazgos);
      // El conteo declarado debe coincidir con el real.
      if (p.hallazgos_abiertos !== abiertos) {
        anomalias.push({
          codigo: "hallazgos_abiertos_distinto",
          detalle: `Evento ${p.hallazgos_abiertos}, real ${abiertos}.`,
        });
      }
      // Con un bloqueante abierto el estado nunca puede ser "aprobada".
      if (p.estado_revision === "aprobada" && hayBloqueanteAbierto(estado.hallazgos)) {
        anomalias.push({
          codigo: "aprobada_con_bloqueante_abierto",
          detalle: "Estado 'aprobada' con un hallazgo bloqueante abierto.",
        });
      }
      return resultado({ revision: p }, anomalias);
    }

    case "aprobada":
      return resultado({
        decision: { seq: evento.seq, comentario: evento.payload.comentario, excepcion: evento.payload.excepcion },
      });

    case "asesoria":
      // Se guarda la asesoría completa; sus alertas se muestran junto a cada slide.
      return resultado({ asesor: { ...evento.payload, seq: evento.seq } });

    case "rechazada":
      return resultado({
        decision: { seq: evento.seq, rechazo: { ...evento.payload, slide: evento.slide } },
      });

    case "editada": {
      if (evento.slide === undefined) return sinSlide(evento.tipo);
      const p = evento.payload;
      const anomalias: { codigo: CodigoAnomalia; detalle: string }[] = [];
      const dibujado = estado.lienzo.textos[evento.slide]?.[p.campo];
      // El "antes" declarado debe ser lo que realmente estaba dibujado.
      if (dibujado !== p.texto_antes) {
        anomalias.push({
          codigo: "editada_texto_antes_distinto",
          detalle: `Slide ${evento.slide}, campo ${p.campo}: antes declarado no coincide con lo dibujado.`,
        });
      }
      // Una edición debe cambiar algo (el esquema dice "deben diferir").
      if (p.texto_antes === p.texto_despues) {
        anomalias.push({
          codigo: "editada_sin_cambio",
          detalle: `Slide ${evento.slide}, campo ${p.campo}: antes y después son iguales.`,
        });
      }
      return resultado(
        {
          lienzo: {
            ...estado.lienzo,
            textos: conCampo(estado.lienzo.textos, evento.slide, p.campo, p.texto_despues),
          },
          ediciones: [
            ...estado.ediciones,
            {
              seq: evento.seq,
              slide: evento.slide,
              campo: p.campo,
              texto_antes: p.texto_antes,
              texto_despues: p.texto_despues,
            },
          ],
        },
        anomalias,
      );
    }

    case "run_finalizada": {
      const calculado = calcularSello(estado.ledger);
      // El sello final también se contrasta con el calculado.
      const anomalias = mismoSello(evento.payload.sello, calculado)
        ? []
        : [
            {
              codigo: "sello_distinto" as const,
              detalle: `Final ${evento.payload.sello.afirmaciones_respaldadas}/${evento.payload.sello.afirmaciones_totales}, calculado ${calculado.afirmaciones_respaldadas}/${calculado.afirmaciones_totales}.`,
            },
          ];
      return resultado({ final: evento.payload }, anomalias);
    }

    default: {
      // Tipo desconocido: el seq avanza (ya aplicado en los metadatos) y se anota.
      const tipo = String((evento as { tipo: unknown }).tipo);
      return resultado({}, [
        { codigo: "tipo_desconocido", detalle: `Tipo de evento desconocido: ${tipo}.` },
      ]);
    }
  }
}

// Reductor principal. Devuelve el MISMO objeto cuando el evento no cambia nada.
export function reducir(estado: Estado, evento: Evento): Estado {
  // 1) Otro run_id: se ignora el evento y se registra la anomalía.
  if (estado.runId !== null && evento.run_id !== estado.runId) {
    const anomalia: Anomalia = {
      seq: evento.seq,
      codigo: "run_distinto",
      detalle: `Evento del run ${evento.run_id}; el estado es del run ${estado.runId}.`,
    };
    return { ...estado, anomalias: [...estado.anomalias, anomalia] };
  }

  // 2) Idempotencia: un seq ya aplicado no cambia nada.
  if (evento.seq <= estado.ultimoSeq) return estado;

  // 3) Estrictez: un salto no se aplica, solo marca el hueco.
  const esperado = estado.ultimoSeq + 1;
  if (evento.seq !== esperado) {
    // Si el hueco ya estaba marcado igual, no se crea un objeto nuevo.
    if (estado.hueco?.esperado === esperado && estado.hueco.recibido === evento.seq) {
      return estado;
    }
    return { ...estado, hueco: { esperado, recibido: evento.seq } };
  }

  // 4) Metadatos comunes a todo evento aplicado.
  const origenes: readonly Origen[] = estado.origenes.includes(evento.origen)
    ? estado.origenes
    : [...estado.origenes, evento.origen];
  const base: Estado = {
    ...estado,
    ultimoSeq: evento.seq,
    hueco: null,
    runId: estado.runId ?? evento.run_id,
    origenes,
    agentes: { ...estado.agentes, [evento.agente]: { tipo: evento.tipo, seq: evento.seq } },
    slideActivo: evento.slide ?? estado.slideActivo,
  };

  // 5) Efecto propio del tipo y anomalías detectadas.
  const { parche, anomalias } = aplicarTipo(base, evento);
  const nuevas: Anomalia[] = anomalias.map((a) => ({ seq: evento.seq, ...a }));
  return {
    ...base,
    ...parche,
    anomalias: nuevas.length > 0 ? [...base.anomalias, ...nuevas] : base.anomalias,
  };
}

// Aplica una lista de eventos en orden y devuelve el estado final.
export function reducirTodos(estado: Estado, eventos: readonly Evento[]): Estado {
  let actual = estado;
  for (const evento of eventos) {
    // Cada evento pasa por las mismas reglas que en vivo.
    actual = reducir(actual, evento);
  }
  return actual;
}