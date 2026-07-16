# Paquete 4E — conversión automática del snapshot APROBADO a PDF

## Resumen

El Paquete 4E agrega la generación de un PDF aprobado sin firmas digitales a partir del snapshot DOCX `APROBADO`. El documento y su versión permanecen en estado `APROBADO`; el paso a `VIGENTE` y las firmas digitales quedan fuera de este paquete.

La conversión está deshabilitada por defecto mediante `ONLYOFFICE_CONVERSION_ENABLED=false`.

## Fuente oficial

La única fuente aceptada para convertir es un `DocumentoSnapshot` que cumpla:

- `tipo == APROBADO`;
- `estado == DISPONIBLE`;
- `inmutable == true`;
- relación válida con `Documento` y `DocumentoVersion`;
- evento de workflow `APROBAR` asociado;
- archivo DOCX privado existente;
- hash SHA-256 físico consistente.

No se convierte la copia de trabajo ni snapshots `ENVIO_REVISION` o `RECHAZADO`.

## Modelos

Se usan dos modelos:

- `DocumentoArtefacto`: representa el PDF definitivo privado e inmutable.
- `DocumentoConversion`: representa el proceso de conversión, progreso, reintentos y errores.

Esta separación evita mezclar evidencia final con proceso recuperable.

## Migración

La migración `c4e7a9d1b2f3_documento_pdf_conversion.py` crea:

- `documento_artefactos`;
- `documento_conversiones`;
- claves foráneas multiempresa;
- checks de estados, hash, tamaño, páginas e inmutabilidad;
- índices de consulta;
- índice único parcial para impedir más de un `PDF_APROBADO` disponible por snapshot.

## Provider abstraction

`DocumentConversionProvider` define el contrato conceptual. `OnlyOfficeConversionProvider` implementa:

- `POST /converter`;
- JSON;
- `filetype=docx`;
- `outputtype=pdf`;
- `async=true`;
- `key` estable;
- `Accept: application/json`;
- interpretación estricta de `endConvert`, `percent`, `fileType`, `fileUrl` y `error`.

El workflow no usa HTTP directamente.

## JWT y URL fuente

La descarga del snapshot fuente por ONLYOFFICE usa un JWT específico con scope:

`onlyoffice:conversion:source`

No reutiliza tokens de visualización, edición, callback ni ping.

La URL técnica es:

`/documentacion/integraciones/onlyoffice/snapshots/<public_id>/conversion-source`

Se construye con `ONLYOFFICE_CALLBACK_BASE_URL` y valida tenant, snapshot, hash, tipo, estado, inmutabilidad, relaciones y archivo físico.

## Conversion key

La clave se calcula de forma estable y opaca con SHA-256 a partir de:

- empresa;
- documento;
- versión;
- `snapshot.public_id`;
- `snapshot.archivo_sha256`;
- tipo `PDF_APROBADO`.

Un reintento usa la misma key.

## Flujo automático

Después del commit exitoso de aprobación:

1. se recupera o crea la conversión;
2. se solicita conversión a ONLYOFFICE;
3. si termina, se descarga y valida el PDF;
4. se guarda en storage privado;
5. se marca el artefacto `DISPONIBLE`;
6. si falla, el workflow permanece aprobado y la conversión queda en `ERROR`.

La llamada HTTP externa no participa en la transacción del workflow.

## Storage e inmutabilidad

El PDF se guarda bajo el área privada de documentos, en subdirectorio `pdf/`, con nombre derivado de hashes. No usa `/static`, hard links ni symlinks. Un artefacto `DISPONIBLE` no se sobrescribe y queda marcado como inmutable en DB, con defensa adicional read-only en filesystem.

## Validación PDF

La validación comprueba:

- encabezado `%PDF-`;
- marcador `%%EOF`;
- tamaño positivo y límite máximo;
- ausencia de cifrado;
- ausencia de contenido activo inesperado;
- conteo de páginas mayor que cero cuando está habilitado.

Deuda técnica: el entorno actual no tenía `pypdf` instalado y `requirements.txt` no pudo editarse con `apply_patch` por encoding no UTF-8. Se recomienda normalizar ese archivo y fijar `pypdf` para reforzar parseo estructural en el siguiente ajuste técnico.

## UI

El detalle documental muestra sección “PDF aprobado” con:

- pendiente;
- convirtiendo con porcentaje;
- disponible;
- error;
- reintento autorizado;
- indicación “PDF aprobado sin firmas digitales”.

No muestra rutas internas, tokens, secrets, URL del proveedor ni conversion key.

## Visor y descarga

Rutas:

- ver inline: `/documentacion/<documento_id>/versiones/<version_id>/pdf-aprobado/ver`;
- descargar: `/documentacion/<documento_id>/versiones/<version_id>/pdf-aprobado/descargar`.

Ambas validan login, tenant, documento, versión, artefacto disponible, snapshot fuente y hash físico. La descarga usa el permiso existente `documentos.descargar`.

## Reintentos y recuperación

La ruta `POST /documentacion/conversiones/<public_id>/actualizar` permite continuar o reintentar procesos según estado y permisos. El CLI `flask documentos conversiones-pendientes` lista procesos pendientes; con `--procesar` intenta reanudarlos.

## Multiempresa

Todas las consultas filtran `empresa_id` y validan relaciones entre usuario, documento, versión, snapshot, conversión y artefacto.

## Condiciones para 4F

4F puede partir del `DocumentoArtefacto` `PDF_APROBADO` `DISPONIBLE`. El PDF no contiene firmas digitales, no tiene páginas de firma añadidas y no cambia el estado documental a `VIGENTE`.
