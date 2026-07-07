# Guion de demo final del módulo documental

Duración sugerida: 10 a 15 minutos.

## 1. Ingreso al sistema

Ingresar con un usuario con permisos documentales. Explicar que el sistema trabaja por empresa, por lo que los documentos visibles pertenecen únicamente a la empresa actual.

## 2. Dashboard documental

Abrir “Dashboard documental”. Mostrar los indicadores principales:

- total de documentos;
- documentos en borrador;
- documentos en revisión;
- vigentes;
- rechazados;
- obsoletos;
- en actualización;
- pendientes;
- documentos sin archivo.

## 3. Alerta de pendientes

Mostrar la alerta visual y explicar que sirve para que Calidad o Administración identifique documentos listos para revisión.

## 4. Creación de documento como técnico

Ingresar como usuario técnico o explicar el rol. Crear un documento nuevo, completar datos básicos y dejarlo en `BORRADOR`.

## 5. Envío a revisión

Desde el detalle, enviar el documento a revisión. Mostrar el cambio a `EN_REVISION`.

## 6. Ingreso como calidad/admin

Cambiar a un usuario `CALIDAD` o `ADMINISTRADOR`. Mostrar que el pendiente aparece en el sidebar, dashboard y bandeja de pendientes.

## 7. Bandeja de pendientes

Entrar a “Mis pendientes”. Mostrar código, título, versión y fecha de envío.

## 8. Aprobación o rechazo

Ejecutar una aprobación si se quiere mostrar el camino exitoso. Alternativamente, rechazar con comentario para demostrar control de observaciones.

## 9. Versión vigente

Mostrar que el documento aprobado queda con una versión vigente. Explicar que `APROBADO` es el estado técnico de la versión y `VIGENTE` es la versión oficial en uso.

## 10. Nueva versión en actualización

Crear una nueva versión sobre el documento vigente. Mostrar que el documento conserva su versión vigente pero aparece funcionalmente como `EN ACTUALIZACIÓN`.

## 11. Obsolescencia

Obsoletar un documento aprobado indicando motivo. Mostrar que pasa a Archivo Documental.

## 12. Historial

Abrir el detalle y revisar historial de versiones y eventos: creación, envío, aprobación, rechazo, devolución, sustitución y obsolescencia.

## 13. Descarga protegida

Descargar una versión como usuario autorizado. Explicar que el archivo no se sirve directamente desde `/static`, sino mediante descarga protegida por sesión y permisos.

## 14. Cierre con beneficios ISO 17025

Cerrar destacando:

- control de documentos vigentes;
- trazabilidad completa;
- separación de roles;
- evidencia para auditoría;
- reducción de uso accidental de versiones obsoletas;
- base lista para ampliar con notificaciones o asignación nominal en paquetes futuros.
