# MultiagentContentCreation

Plataforma de agentes que convierte una fuente técnica (PDF, URL, documento) en un carrusel de Instagram, con un revisor editorial explicable que verifica la fidelidad a la fuente. Un renderizador determinista dibuja el diseño en vivo mientras los agentes trabajan.

Estado: **Fase 0 (fundamentos)**. Ver `SPEC.md` para decisiones, esquema de entrada y estructura de carpetas, y `docs/roadmap.md` para las fases.

## Estructura

* `contracts/`: esquemas compartidos (eventos, entrada, ficha de plantilla, kit de marca), secuencias grabadas y `validate.py`
* `templates/`: plantillas, paletas, tipografías, estilos y kit de marca
* `backend/`: API, agentes, grafo, fuentes, revisor, render (aún vacío; Fase 1 en adelante)
* `frontend/`: lienzo, línea de tiempo, controles, panel de revisión (aún vacío)
* `eval/`: conjunto de prueba del revisor y resultados
* `deploy/`: Nginx y OCI
* `docs/`: decisiones, roadmap y licencias

## Regla de dependencia

`frontend` y `backend` solo se comunican a través de `contracts/`.

## Validar los contratos

```
pip install -r requirements.txt
python contracts/validate.py
```

El validador comprueba: esquemas JSON Schema 2020-12 bien formados, `$comment` en cada bloque, ejemplos de entrada válidos e inválidos, ficha de plantilla, kit de marca (con contrastes recalculados) y la secuencia grabada (orden por `seq`, causas, citas literales contra la fuente y sello de revisión).
