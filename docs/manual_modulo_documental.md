# Manual corto de usuario del módulo documental

## Objetivo

El módulo documental permite controlar documentos del sistema de gestión del laboratorio: políticas, procedimientos, instructivos, manuales, formatos y registros. Su propósito es mantener versiones, estados, responsables y trazabilidad del ciclo de vida documental.

## Estados documentales

- `EN_ELABORACION`: documento o versión en preparación.
- `EN_REVISION`: documento enviado para revisión o aprobación.
- `RECHAZADO`: versión observada que requiere corrección.
- `APROBADO`: versión aprobada.
- `OBSOLETO`: documento retirado del uso.
- `SUSTITUIDO`: versión aprobada anterior reemplazada por una nueva.

## APROBADO vs VIGENTE

Una versión `APROBADA` es una versión que superó la revisión. Un documento es `VIGENTE` cuando su campo de versión vigente apunta a una versión aprobada activa. En la práctica, â€œvigenteâ€ es la versión oficial que debe usarse.

## VIGENTE vs EN ACTUALIZACIÓN

Un documento puede tener una versión vigente y, al mismo tiempo, una nueva versión en preparación. En ese caso el documento sigue teniendo una versión oficial vigente, pero funcionalmente está `EN ACTUALIZACIÓN`.

## Crear documento

1. Entrar a Gestión Documental.
2. Seleccionar â€œNuevo documentoâ€.
3. Completar código, título, tipo documental, proceso y versión.
4. Adjuntar archivo si aplica.
5. Guardar.

El documento queda inicialmente en `EN_ELABORACION`.

## Subir archivo

Al crear un documento o una nueva versión, puede adjuntarse un archivo. Los archivos se almacenan en el storage privado del sistema y se descargan mediante rutas protegidas.

## Enviar a revisión

Desde el detalle del documento, usar la acción â€œEnviar a revisiónâ€. El documento pasa a `EN_REVISION` y queda visible para usuarios con rol de revisión/aprobación.

## Revisar pendientes

Los usuarios autorizados pueden entrar a â€œMis pendientesâ€ o al dashboard documental para revisar documentos en estado `EN_REVISION`.

## Aprobar documento

Un usuario autorizado puede aprobar una versión en revisión. Al aprobar:

- la versión queda `APROBADA`;
- el documento queda con versión vigente;
- si existía una versión vigente previa, queda sustituida cuando corresponde.

## Rechazar documento

El rechazo requiere comentario. La versión queda `RECHAZADO` y el comentario queda registrado en la trazabilidad.

## Devolver a elaboración

Una versión rechazada puede devolverse a `EN_ELABORACION` para corrección. Esta acción también requiere comentario.

## Crear nueva versión

Desde un documento aprobado, seleccionar â€œNueva versiónâ€. La versión vigente anterior se mantiene como oficial mientras la nueva versión se prepara, revisa y aprueba.

## Obsoletar documento

Un documento aprobado puede marcarse como obsoleto con motivo obligatorio. El documento pasa a Archivo Documental y deja de tener versión vigente activa.

## Consultar historial

El historial muestra versiones y eventos del workflow: creación, envío a revisión, aprobación, rechazo, devolución, sustitución y obsolescencia.

## Descargar documento

Los usuarios con permiso de descarga pueden descargar versiones documentales desde el detalle del documento. La descarga está protegida por autenticación y permisos.

## Usar dashboard documental

El dashboard documental muestra:

- total de documentos;
- conteos por estado;
- documentos vigentes;
- documentos en actualización;
- pendientes de revisión/aprobación;
- documentos recientes;
- obsoletos recientes;
- documentos sin archivo asociado;
- conteos por tipo documental.

## Roles y permisos

- `ADMINISTRADOR` y `CALIDAD`: pueden revisar, aprobar, rechazar, devolver, obsoletar y consultar pendientes.
- `TECNICO`: puede crear, editar documentos permitidos, enviar a revisión, ver historial y descargar.
- `CONSULTA`: puede ver y descargar documentos, sin modificar el workflow.

## Recomendaciones de uso

- Usar códigos documentales consistentes.
- Registrar comentarios claros en rechazos, devoluciones y obsolescencias.
- Evitar crear nuevas versiones si ya existe una versión en preparación.
- Verificar el dashboard antes de una auditoría.
- Mantener los documentos obsoletos con motivo documentado.
