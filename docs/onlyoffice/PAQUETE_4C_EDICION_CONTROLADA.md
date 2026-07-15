# Paquete 4C — Edición controlada en ONLYOFFICE

## Arquitectura

La edición DOCX se implementa sobre la copia de trabajo privada ya registrada en `DocumentoVersion`. No se crea otro `Documento` ni otra `DocumentoVersion` durante guardados intermedios o finales.

Componentes principales:

- `DocumentoEdicion`: sesión de edición y bloqueo exclusivo.
- `DocumentoEdicionEvento`: auditoría e idempotencia de callbacks.
- `OnlyOfficeDocumentEditService`: validación de elegibilidad, adquisición de bloqueo y configuración del editor.
- `OnlyOfficeEditSessionService`: heartbeat, liberación y solicitud backend de forcesave.
- `OnlyOfficeCallbackService`: validación de callback, SSRF, descarga, validación DOCX y guardado atómico.

## Modelo de sesión

Una sesión mantiene:

- `public_id` opaco para URLs;
- `editor_key` estable para ONLYOFFICE durante la sesión;
- `hash_inicial`;
- `hash_ultimo_guardado`;
- estado de sesión independiente del estado documental;
- timestamps de inicio, actividad, expiración, liberación, callback y guardado;
- último fingerprint de callback.

Estados:

- `ACTIVA`
- `LIBERADA`
- `EXPIRADA`
- `ERROR`
- `CANCELADA`

## Migración

La migración `a7c9e4d2f6b1_onlyoffice_edicion_controlada.py` crea:

- `documento_ediciones`;
- `documento_edicion_eventos`;
- índices por documento, versión, usuario, estado y expiración;
- `public_id` único;
- `editor_key` único;
- índice único parcial para impedir más de una sesión `ACTIVA` por `documento_version_id`.

## Bloqueo exclusivo

La edición se permite solo para la versión activa de preparación en estado `EN_ELABORACION`.

Casos:

- sin sesión activa: crea sesión nueva;
- misma persona: reutiliza sesión y renueva TTL;
- otra persona: bloquea edición y permite lectura;
- sesión vencida: se marca `EXPIRADA` y se permite nueva adquisición;
- sesión en error: no se trata como editable automáticamente.

## TTL y heartbeat

Variables:

- `ONLYOFFICE_EDIT_LOCK_TTL_SECONDS`
- `ONLYOFFICE_EDIT_HEARTBEAT_SECONDS`

El heartbeat renueva `ultima_actividad` y `fecha_expiracion`. Si vence el TTL, la sesión puede recuperarse como expirada.

## Editor key

`editor_key` no se basa en el hash del archivo. Es estable durante la sesión y cambia en una nueva sesión, evitando que los guardados rompan la sesión al cambiar el hash.

## Callback

La callback URL usa `public_id` opaco:

`/documentacion/integraciones/onlyoffice/ediciones/<public_id>/callback`

No expone:

- empresa;
- documento;
- versión;
- storage path;
- hash;
- usuario.

El callback requiere JWT con scope `onlyoffice:document:callback`.

## Estados ONLYOFFICE

- `1`: actividad, renueva sesión.
- `2`: guardado final, descarga, reemplaza copia de trabajo y libera.
- `3`: error de guardado final, registra error.
- `4`: cierre sin cambios, libera sin guardar.
- `6`: guardado forzado, descarga, reemplaza copia de trabajo y mantiene sesión activa.
- `7`: error de guardado forzado, registra error sin reemplazar.

## Idempotencia

Cada callback genera fingerprint con:

- `public_id`;
- `key`;
- `status`;
- `forcesavetype`;
- URL normalizada;
- presencia de history.

Si el fingerprint ya fue procesado, responde `{"error": 0}` sin descargar ni reescribir.

## SSRF

La URL de resultado se trata como no confiable. Solo se aceptan `http`/`https` y hosts permitidos por:

- `ONLYOFFICE_ALLOWED_HOSTS`;
- host de `ONLYOFFICE_INTERNAL_URL`;
- host de `ONLYOFFICE_PUBLIC_URL`.

Se vuelve a validar la URL final después de redirects.

## Validación DOCX

El archivo descargado debe ser ZIP OOXML válido y contener:

- `[Content_Types].xml`;
- `word/document.xml`.

## Guardado atómico

El guardado:

1. descarga a temporal seguro;
2. valida DOCX;
3. calcula hash y tamaño;
4. confirma sesión activa;
5. confirma versión `EN_ELABORACION`;
6. confirma hash esperado;
7. crea reemplazo temporal y backup;
8. usa `os.replace`;
9. actualiza `archivo_sha256`, `archivo_size` y MIME;
10. registra auditoría.

Si falla el filesystem, restaura la copia anterior. Si falla la base, se conservan metadatos previos en la sesión transaccional.

## Forcesave

El navegador no envía comandos directos a ONLYOFFICE. Llama a:

`POST /documentacion/ediciones/<public_id>/forcesave`

LabZenISO valida sesión y solicita `forcesave` al Command Service. El guardado real se confirma solo cuando llega callback status `6`.

## Recuperación

La sesión vencida pasa a `EXPIRADA`. Otro usuario puede adquirir una nueva sesión después de que el servicio marca la anterior como expirada.

## Auditoría

Se registran eventos de:

- sesión iniciada;
- bloqueo renovado;
- heartbeat;
- guardado forzado solicitado;
- guardado forzado completado;
- guardado final;
- cierre sin cambios;
- error de callback;
- sesión expirada;
- liberación voluntaria;
- liberación administrativa.

No se registran JWT, secrets, contenido documental ni rutas absolutas.

## Permisos y multiempresa

La edición requiere:

- autenticación;
- `documentos.editar`;
- empresa del documento igual a `current_user.empresa_id`;
- versión perteneciente al documento y empresa.

La liberación administrativa usa el permiso existente `documentos.ver_historial`.

## Integración workflow

No se cambian transiciones. Solo se agrega un guard en envío a revisión:

si existe sesión activa de edición, se rechaza con mensaje controlado.

## Limitaciones

- No implementa PDF.
- No implementa firmas digitales.
- No habilita control formal de cambios.
- No habilita coedición libre.
- La confirmación visual de “Guardado” depende de callback status `6` o `2`.

## Condiciones para Paquete 4D

Iniciar 4D solo cuando:

- callback real status `6` y `2` haya sido validado manualmente;
- bloqueo con dos usuarios haya sido validado en navegador;
- fidelidad del DOCX real haya sido revisada sin publicar contenido.
