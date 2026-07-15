# Paquete 4D - Snapshots documentales y workflow

## Alcance

Este paquete congela copias DOCX auditables durante el workflow documental sin crear nuevas versiones logicas.

- `ENVIO_REVISION`: copia fisica independiente de la copia de trabajo al enviar a revision.
- `APROBADO`: copia fisica independiente tomada desde el snapshot de revision aprobado.
- `RECHAZADO`: marcador auditable que referencia el snapshot de revision rechazado.

No implementa PDF, firmas digitales, MinIO, Redis ni nuevos permisos.

## Regla operativa

La copia de trabajo vive en `documento_versiones.archivo_storage_path`.
Los snapshots viven bajo el mismo storage privado, dentro de:

`empresa_<id>/documento_<id>/v<version>/snapshots/`

El visor y la descarga usan la fuente oficial segun estado:

- `EN_ELABORACION`: copia de trabajo.
- `EN_REVISION`: ultimo snapshot `ENVIO_REVISION`.
- `APROBADO`: snapshot `APROBADO`.
- `RECHAZADO`: marcador `RECHAZADO`, resuelto hacia su snapshot origen.

## Inmutabilidad

Cada snapshot disponible guarda:

- hash SHA-256;
- tamano;
- MIME;
- ruta privada;
- ciclo de revision;
- secuencia;
- usuario creador;
- evento de workflow asociado cuando aplica.

El servicio valida que el archivo fisico coincida con el hash y tamano registrados antes de servirlo.

## Integracion con workflow

- Enviar a revision exige resumen de modificaciones y hojas modificadas, bloquea sesiones ONLYOFFICE activas/error y crea snapshot antes de cambiar estado.
- Aprobar exige snapshot de revision y crea snapshot aprobado antes de marcar la version como vigente.
- Rechazar crea marcador auditable y conserva el snapshot revisado.
- Devolver a borrador restaura la copia de trabajo desde el ultimo snapshot de revision cuando la copia editable diverge.

## Seguridad

- Las rutas fisicas no se exponen al navegador.
- ONLYOFFICE recibe URLs protegidas por JWT.
- El JWT de lectura puede incluir `snapshot_public_id` para servir el snapshot oficial.
- Edicion, descarga e impresion siguen deshabilitadas en el visor de lectura.

