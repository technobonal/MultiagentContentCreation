// ---------------------------------------------------------------------------
// avatares.tsx — Avatares originales de los agentes (SVG propio, sin imágenes).
// Cada uno es un personaje geométrico con su color y su herramienta:
// brújula (estratega), pluma (redactor), pincel (director de arte), lupa (revisor),
// sello de aprobar (humano) y engranaje (sistema).
// Las animaciones (flotar, parpadear, mover la herramienta) viven en style.css.
// ---------------------------------------------------------------------------

// Agentes que tienen avatar, en el orden de la fila de reposo.
export const AGENTES_AVATAR: readonly string[] = [
  "estratega",
  "redactor",
  "director_arte",
  "revisor",
  "humano",
  "sistema",
];

// Color propio de cada agente (se aplica con currentColor).
export const COLOR_AGENTE: Readonly<Record<string, string>> = {
  estratega: "#A78BFA",
  redactor: "#38BDF8",
  director_arte: "#F472B6",
  revisor: "#FBBF24",
  humano: "#4ADE80",
  sistema: "#94A3B8",
};

// Color de respaldo para un agente desconocido.
const COLOR_RESPALDO = "#38BDF8";

// Dibuja la herramienta de un agente en la esquina inferior derecha del personaje.
function Herramienta({ agente }: { agente: string }) {
  switch (agente) {
    case "estratega":
      // Brújula: círculo con aguja.
      return (
        <g className="herramienta">
          <circle cx="39" cy="38" r="6.5" fill="#0F172A" stroke="currentColor" strokeWidth="2" />
          <path d="M39 33 L41 38 L39 43 L37 38 Z" fill="currentColor" />
        </g>
      );
    case "redactor":
      // Pluma: cuerpo diagonal con la punta clara.
      return (
        <g className="herramienta">
          <path d="M34 46 L36 40 L44 32 L47 35 L39 43 Z" fill="currentColor" />
          <path d="M34 46 L36 40 L39 43 Z" fill="#F8FAFC" />
        </g>
      );
    case "director_arte":
      // Pincel: mango diagonal y punta de pintura.
      return (
        <g className="herramienta">
          <line x1="35" y1="45" x2="43" y2="34" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          <circle cx="44.5" cy="32" r="3.5" fill="#F8FAFC" />
        </g>
      );
    case "revisor":
      // Lupa: lente y mango.
      return (
        <g className="herramienta">
          <circle cx="39" cy="37" r="5.5" fill="#0F172A" stroke="currentColor" strokeWidth="2.5" />
          <line x1="43" y1="41" x2="47" y2="45" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </g>
      );
    case "humano":
      // Sello de aprobar: disco con visto.
      return (
        <g className="herramienta">
          <circle cx="40" cy="38" r="7" fill="currentColor" />
          <path d="M36.5 38 L39 41 L44 35" stroke="#0F172A" strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      );
    case "sistema":
      // Engranaje: aro con dientes (trazo punteado) y centro.
      return (
        <g className="herramienta">
          <circle cx="40" cy="38" r="6" fill="none" stroke="currentColor" strokeWidth="4" strokeDasharray="2.4 2.4" />
          <circle cx="40" cy="38" r="3" fill="#0F172A" stroke="currentColor" strokeWidth="2" />
        </g>
      );
    default:
      // Agente desconocido: sin herramienta.
      return null;
  }
}

// Avatar completo de un agente; `tamano` es el lado en px.
export function Avatar({ agente, tamano = 44 }: { agente: string; tamano?: number }) {
  const color = COLOR_AGENTE[agente] ?? COLOR_RESPALDO;
  // El humano tiene la cabeza más redonda que los robots.
  const radio = agente === "humano" ? 16 : 10;

  return (
    <svg viewBox="0 0 48 48" width={tamano} height={tamano} style={{ color }} aria-hidden="true">
      {/* Antena. */}
      <line x1="24" y1="6" x2="24" y2="11" stroke="currentColor" strokeWidth="2" />
      <circle cx="24" cy="5" r="3" fill="currentColor" />

      {/* Cabeza. */}
      <rect x="8" y="11" width="32" height="26" rx={radio} fill="#0F172A" stroke="currentColor" strokeWidth="2.5" />

      {/* Ojos (parpadean por CSS). */}
      <circle className="ojo" cx="18" cy="23" r="3" fill="currentColor" />
      <circle className="ojo" cx="30" cy="23" r="3" fill="currentColor" />

      {/* Sonrisa. */}
      <path d="M18 30 Q24 34 30 30" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />

      {/* Herramienta propia del agente. */}
      <Herramienta agente={agente} />
    </svg>
  );
}