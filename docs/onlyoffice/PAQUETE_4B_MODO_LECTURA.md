# PAQUETE 4B — Visualización DOCX en modo lectura

## Objetivo

Abrir versiones DOCX dentro de LabZenISO usando ONLYOFFICE Docs en modo lectura, sin editar, sin guardar, sin callback de guardado, sin crear versiones y sin modificar el workflow documental.

## Arquitectura

El visor se compone de tres piezas:

- Ruta autenticada de usuario para abrir el visor.
- Servicio `OnlyOfficeDocumentViewService` para construir configuración segura.
- Ruta técnica tokenizada para que ONLYOFFICE descargue el DOCX desde el storage privado.

El archivo sigue almacenado en el filesystem privado actual. No se usa `/static`, `/uploads` ni `file://`.

## Rutas

Visor autenticado:

```text
GET /documentacion/<documento_id>/versiones/<version_id>/onlyoffice/ver
```

Entrega técnica del DOCX:

```text
GET /documentacion/integraciones/onlyoffice/versiones/<version_id>/archivo?token=<jwt>
```

La ruta técnica no depende de cookies Flask. Usa un JWT temporal específico para el documento.

## JWT documental

Scope:

```text
onlyoffice:document:view
```

Claims principales:

- `iss`
- `aud`
- `iat`
- `nbf`
- `exp`
- `jti`
- `scope`
- `empresa_id`
- `documento_id`
- `version_id`
- `archivo_sha256`

El token no contiene secretos ni rutas privadas.

## TTL

Variable:

```env
ONLYOFFICE_DOCUMENT_TOKEN_TTL_SECONDS=300
```

Debe ser un entero positivo.

## Key de ONLYOFFICE

La key se construye como SHA-256 opaco de:

```text
empresa_id + documento_id + version_id + archivo_sha256
```

No contiene código, título, nombre de archivo ni rutas.

## Configuración del editor

Se fuerza:

```json
{
  "documentType": "word",
  "document": {
    "fileType": "docx",
    "permissions": {
      "edit": false,
      "download": false,
      "print": false,
      "review": false,
      "comment": false,
      "fillForms": false,
      "modifyFilter": false
    }
  },
  "editorConfig": {
    "mode": "view"
  }
}
```

No se incluye `callbackUrl`.

La configuración completa se firma con `ONLYOFFICE_JWT_SECRET` y se entrega a la API de ONLYOFFICE en el campo `token`.

## CSP

El visor agrega una política CSP específica para su respuesta y permite únicamente el origen configurado en:

```env
ONLYOFFICE_PUBLIC_URL
```

No se agrega CORS global abierto.

## Seguridad y multiempresa

La ruta del visor:

- requiere login;
- requiere permiso `documentos.ver`;
- filtra `Documento` por `current_user.empresa_id`;
- filtra `DocumentoVersion` por documento y empresa;
- rechaza DOCX inexistente, hash ausente o storage path inválido.

La ruta técnica:

- valida firma JWT;
- valida expiración;
- valida scope;
- valida empresa, documento, versión y hash contra la base;
- usa `resolve_document_path`;
- no expone rutas privadas;
- no lista directorios.

## Manejo de errores

Casos controlados:

- ONLYOFFICE deshabilitado;
- ONLYOFFICE no disponible;
- documento inexistente;
- versión inexistente;
- documento de otra empresa;
- archivo no DOCX;
- archivo privado inexistente;
- token ausente;
- token inválido;
- token vencido;
- scope incorrecto;
- hash inconsistente.

## Prueba manual

1. Confirmar que ONLYOFFICE esté healthy:

```text
http://localhost:8082/healthcheck
```

2. Iniciar Flask escuchando en todas las interfaces locales:

```bash
python -m flask run --host=0.0.0.0 --port=5001
```

3. Entrar a LabZenISO desde el navegador:

```text
http://127.0.0.1:5001
```

4. Abrir un documento con versión DOCX almacenada por el flujo normal.
5. Presionar `Ver en ONLYOFFICE`.
6. Confirmar que el documento aparece dentro de LabZenISO.
7. Confirmar que se muestra `Modo lectura`.
8. Confirmar que no se puede editar.
9. Confirmar que el editor no ofrece descarga ni impresión.
10. Volver al detalle.
11. Verificar que no cambió estado, versión, hash ni archivo.

## Prueba con el DOCX real del cliente

No abrir ni servir directamente `docs/cliente`.

Para una prueba real:

1. Verificar hash del original.
2. Crear una copia temporal fuera del repositorio.
3. Cargarla por el flujo normal de LabZenISO para que entre al storage privado.
4. Abrir la versión desde `Ver en ONLYOFFICE`.
5. Validar fidelidad visual sin capturas ni divulgación de contenido.
6. Confirmar que el hash del original no cambió.
7. Eliminar temporales fuera del storage controlado.

## Fidelidad visual a revisar

Registrar solo estado de validación:

- encabezado;
- pie de página;
- logotipo;
- tablas;
- histórico de modificaciones;
- estilos;
- numeración;
- saltos de página;
- márgenes;
- campos automáticos;
- marcadores;
- controles de contenido;
- hipervínculos;
- ecuación;
- fuentes;
- símbolos técnicos;
- orientación;
- cantidad aparente de páginas.

No publicar contenido confidencial.

## Limitaciones

- No hay edición.
- No hay callback de guardado.
- No hay bloqueo.
- No hay snapshots.
- No hay conversión a PDF.
- No hay firma digital.
- No hay persistencia de sesiones de visor.
- La prueba de fidelidad real requiere validación visual manual.

## Condiciones para iniciar PAQUETE 4C

Solo iniciar 4C cuando:

- el modo lectura funcione contra ONLYOFFICE real;
- el archivo se entregue solo mediante token temporal;
- las pruebas automatizadas pasen;
- se valide una copia controlada del DOCX real;
- no existan duplicaciones de Documento/DocumentoVersion;
- se confirme que no hay callback de guardado en 4B.
