# Licencias

Registro de las licencias de las fuentes, imágenes y tipografías que usa el proyecto.

## Caso estrella: The Scrum Guide (2020)

| Campo | Valor |
| ----- | ----- |
| Obra | The Scrum Guide, The Definitive Guide to Scrum: The Rules of the Game |
| Autores | Ken Schwaber y Jeff Sutherland |
| Edición | Noviembre de 2020 |
| Origen | https://scrumguides.org |
| Licencia | Creative Commons Atribución-CompartirIgual 4.0 (CC BY-SA 4.0) |
| Texto de la licencia | https://creativecommons.org/licenses/by-sa/4.0/ |
| Confirmada el | 2026-11-12, en el PDF oficial de scrumguides.org |

**Qué exige la licencia**

- Atribución: acreditar a los autores, enlazar la licencia e indicar que se hicieron cambios.
- Compartir igual: el carrusel es una obra derivada (resume y reformula) y se publica también bajo CC BY-SA 4.0.

**Valores para el slide de fuentes y la entrada**

- `fuente.atribucion`: The Scrum Guide (2020), Ken Schwaber y Jeff Sutherland, scrumguides.org. Resumido y reformulado.
- `fuente.licencia`: CC BY-SA 4.0

Nota: es la lectura habitual de la licencia, no asesoría legal.

## Tipografías del kit de marca

Las dos fuentes se publican bajo la SIL Open Font License 1.1 (OFL), que permite uso comercial e incrustarlas en el render. Los archivos de fuente van en `templates/typography/`, cada uno junto a su `OFL.txt`, porque la OFL pide conservar el texto de la licencia y el aviso de copyright cuando se redistribuyen los archivos (por ejemplo, al subir el repo a GitHub).

| Fuente | Uso | Licencia | Enlace | Estado |
| ------ | --- | -------- | ------ | ------ |
| Inter (variable) | Títulos, subtítulos, cuerpo, CTA y atribución (pesos 400, 600 y 700) | SIL OFL 1.1, copyright 2020 The Inter Project Authors | https://github.com/rsms/inter | Confirmada el 2026-11-13 en `templates/typography/inter/OFL.txt` |
| JetBrains Mono Regular | Sello de revisión (clase `.mono`), solo peso 400 | SIL OFL 1.1, copyright 2020 The JetBrains Mono Project Authors | https://github.com/JetBrains/JetBrainsMono | Confirmada el 2026-11-13 en `templates/typography/jetbrains-mono/OFL.txt` |

Archivos de fuente en el repo:

- `templates/typography/inter/Inter-Variable.ttf`
- `templates/typography/jetbrains-mono/JetBrainsMono-Regular.ttf`

Si se agrega otra fuente o peso, hay que sumar su fila aquí y su `OFL.txt` (o la licencia que traiga) junto al archivo.

Nota: es la lectura habitual de la licencia, no asesoría legal.

## Imágenes

Pendiente (V10). El caso estrella no usa imágenes de terceros; la foto de producto, si existe, entra con licencia `usuario`.