---
name: language-convention
description: "Trigger: codigo en ingles, comentarios en espanol, nombres de funciones, nueva ruta, texto de UI, docstring, en que idioma. Identificadores y UI en ingles, comentarios y docs en espanol."
license: Apache-2.0
metadata:
  author: Kervis
  version: "2.0"
---

## Activation Contract

Cargar antes de crear o renombrar cualquier archivo, ruta, componente, función, modelo, endpoint o texto que vea un usuario. Aplica por igual al backend (Django, Python; repo `torquetrack-backend`) y al frontend (Vite, React, TypeScript; repo `torquetrack-frontend`).

TorqueTrack es una empresa de Estados Unidos y sus clientes y empleados son angloparlantes: el producto es en inglés. Quien mantiene el código es hispanohablante: la explicación es en español.

No aplicar reglas de idioma de otros proyectos.

## Hard Rules

- Identificadores en inglés, en todos los lenguajes: archivos, carpetas, módulos, clases, funciones, métodos, variables, componentes, hooks, tipos, apps de Django, nombres de modelos y campos, fixtures de pytest y claves JSON.
- Rutas y URLs públicas en inglés (`/about`, `/checkout`, `/account`). Nunca slugs en español.
- Todo lo que lee una persona desde el producto va en inglés: textos de pantalla, labels, placeholders, mensajes de validación, toasts, correos, PDFs y el contenido de `{"error": "..."}`.
- **Comentarios y docstrings en español, siempre, en los dos stacks.** Un `#` de Python, un docstring de Django, un `"""` de un service, un `//` de TypeScript y un JSDoc se escriben en español.
- El comentario explica POR QUÉ, no QUÉ. Si el comentario se limita a traducir la línea siguiente, sobra.
- La documentación del repositorio (`docs/`, `skills/`, `AGENTS.md`) se escribe en español, con nombres de archivo en inglés.

## Decision Gates

| Superficie | Idioma |
|---|---|
| Nombres de archivos, carpetas y rutas | Inglés |
| Clases, funciones, variables, componentes, hooks | Inglés |
| Apps, modelos y campos de Django | Inglés |
| Claves JSON y nombres de campos de la API | Inglés |
| Textos de storefront, panel y portal del cliente | Inglés |
| Mensajes de error que llegan al cliente | Inglés |
| Correos y PDFs | Inglés |
| Comentarios `#` y docstrings de Python y Django | Español |
| Comentarios `//` y JSDoc de TypeScript y React | Español |
| Mensajes de commit | Español |
| Documentación en `docs/` y `skills/` | Español |
| Conversación con el desarrollador | Español |

## Execution Steps

1. Nombrar en inglés el archivo, la ruta, la clase y la función antes de escribir la primera línea.
2. Escribir en inglés los textos de UI y los mensajes que devuelve la API.
3. Agregar un comentario en español solo cuando el porqué no se deduce del código: una regla del contrato de la API que parece un error y no lo es, una decisión de seguridad o una restricción legal o fiscal.
4. Revisar el diff antes de cerrar: rechazar cualquier identificador en español, cualquier texto de UI en español y cualquier comentario en inglés.

## Output Contract

Reportar los nombres y rutas creados. Señalar todo identificador o texto de usuario que haya quedado en español, y todo comentario o docstring que haya quedado en inglés.

## References

- `references/examples.md` — ejemplos correctos e incorrectos en Python y en TypeScript.
