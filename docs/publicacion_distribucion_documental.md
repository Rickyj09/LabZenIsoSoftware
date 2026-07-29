# Publicacion y distribucion documental

## Arquitectura

La publicacion documental agrega una fase posterior a la firma PAdES. El orden protegido es:

1. PDF aprobado original inmutable.
2. Publicacion PREPARADA con `public_id` no secuencial.
3. QR PNG local con la URL controlada.
4. Artefacto `PDF_APROBADO_CON_QR` derivado del PDF aprobado.
5. Firmas PAdES incrementales sobre el PDF con QR.
6. Proceso de firma `COMPLETADO`.
7. Accion explicita `Publicar como vigente`.
8. Estado `VIGENTE`, publicacion `ACTIVA` y version anterior `OBSOLETO`.
9. Snapshot de distribucion y cola de correos.

Los PDFs aprobados originales, PDFs firmados existentes y hashes previos no se modifican. Las versiones historicas ya firmadas pueden tener publicacion sin QR embebido.

## Variables de entorno

- `DOCUMENT_PUBLICATION_BASE_URL`: URL base externa para QR y correos.
- `DOCUMENT_PUBLICATION_DEFAULT_ACCESS`: `AUTENTICADO` por defecto.
- `DOCUMENT_PUBLICATION_QR_PAGE`: `first`, `last` o indice desde 1.
- `DOCUMENT_PUBLICATION_QR_BOX`: coordenadas normalizadas `x1,y1,x2,y2`.
- `DOCUMENT_DISTRIBUTION_EMAIL_ENABLED`: `false` por defecto para no enviar SMTP real.
- `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`, `MAIL_TIMEOUT`.

No almacenar secretos reales en `.env.example` ni en logs.

## Proceso de publicacion

La accion `Publicar como vigente` exige version APROBADA, PDF aprobado, proceso de firma COMPLETADO, PDF final firmado, permiso `documentos.publicar_vigente` y misma empresa. La transicion marca la nueva version como `VIGENTE`, guarda `vigente_desde` y `publicado_por_id`, obsoleta la version anterior y conserva la publicacion anterior como trazabilidad.

## Distribucion

La lista por documento admite destinatarios internos de la misma empresa y externos autorizados. Al publicar se copian los activos a `DocumentoDistribucionEntrega`; la restriccion unica por `publicacion_id` y `email_snapshot` evita duplicados ante recargas o reintentos.

## CLI y reintentos

Procesar correos:

```powershell
venv\Scripts\python.exe -m flask distribucion-documental procesar-correos --limite 50
```

Reintentar fallidos:

```powershell
venv\Scripts\python.exe -m flask distribucion-documental procesar-correos --solo-fallidos --max-intentos 3
```

La accion administrativa `Reintentar fallidos` usa el mismo mecanismo y no duplica entregas `ENVIADO`.

## Revocacion

Revocar exige `documentos.publicaciones.revocar` y motivo obligatorio. No borra documentos, firmas, QR ni hashes; solo cambia la publicacion a `REVOCADA` y bloquea la descarga.

## Criterios beta

- Validar QR sobre documentos sinteticos antes de activar tipos reales.
- Confirmar que la caja de QR no cubre contenido ni firmas para cada plantilla.
- Mantener `DOCUMENT_DISTRIBUTION_EMAIL_ENABLED=false` hasta completar SMTP.
- Ejecutar `flask db check` despues de migrar.
- Ejecutar suite documental y prueba visual en cada ajuste de ubicacion.
