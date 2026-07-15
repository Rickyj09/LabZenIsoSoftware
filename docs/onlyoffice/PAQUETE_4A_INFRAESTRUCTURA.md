# PAQUETE 4A — Infraestructura ONLYOFFICE

## Objetivo

Preparar infraestructura local para validar conectividad entre LabZenISO y ONLYOFFICE Docs sin abrir documentos reales, sin editar archivos documentales y sin modificar el workflow documental.

Este paquete solo cubre:

- Docker Compose local para ONLYOFFICE Document Server.
- Variables de entorno seguras.
- Health check desde LabZenISO hacia ONLYOFFICE.
- Endpoint técnico de ping desde ONLYOFFICE hacia LabZenISO.
- Página administrativa de diagnóstico.

No implementa edición, callbacks de guardado, snapshots, conversión a PDF ni firmas digitales.

## Requisitos

- Docker Desktop instalado y en ejecución.
- Docker Compose disponible.
- LabZenISO ejecutándose localmente en Windows, normalmente en:

```text
http://127.0.0.1:5000
```

## Imagen utilizada

```text
onlyoffice/documentserver:8.2.2
```

Se fija una versión explícita para evitar cambios inesperados de `latest`.

## Variables

Crear o ajustar `.env` local, sin agregarlo a Git:

```env
ONLYOFFICE_ENABLED=true
ONLYOFFICE_PUBLIC_URL=http://localhost:8082
ONLYOFFICE_INTERNAL_URL=http://localhost:8082
ONLYOFFICE_CALLBACK_BASE_URL=http://host.docker.internal:5000
ONLYOFFICE_JWT_SECRET=usar-un-secreto-local-largo
ONLYOFFICE_VERIFY_SSL=false
ONLYOFFICE_REQUEST_TIMEOUT_SECONDS=10
ONLYOFFICE_ALLOWED_HOSTS=localhost,127.0.0.1,host.docker.internal
ONLYOFFICE_HEALTHCHECK_PATH=/healthcheck
ONLYOFFICE_PORT=8082
```

No usar secretos reales en `.env.example`.

## Diseño de red local

Hay tres direcciones distintas:

| Flujo | Variable | Valor local recomendado |
|---|---|---|
| Navegador → ONLYOFFICE | `ONLYOFFICE_PUBLIC_URL` | `http://localhost:8082` |
| LabZenISO → ONLYOFFICE | `ONLYOFFICE_INTERNAL_URL` | `http://localhost:8082` |
| ONLYOFFICE → LabZenISO | `ONLYOFFICE_CALLBACK_BASE_URL` | `http://host.docker.internal:5000` |

Desde un contenedor Docker, `127.0.0.1` apunta al propio contenedor. Por eso ONLYOFFICE debe regresar a LabZenISO usando `host.docker.internal`.

## Arranque

```bash
docker compose -f docker-compose.onlyoffice.yml up -d
```

Ver estado:

```bash
docker compose -f docker-compose.onlyoffice.yml ps
```

Ver logs:

```bash
docker compose -f docker-compose.onlyoffice.yml logs --tail=100
```

Parar sin eliminar volúmenes:

```bash
docker compose -f docker-compose.onlyoffice.yml down
```

Limpieza destructiva opcional, solo si se quiere eliminar datos persistentes de ONLYOFFICE:

```bash
docker compose -f docker-compose.onlyoffice.yml down -v
```

No usar `down -v` como parada normal.

## Health check

La página administrativa consulta:

```text
ONLYOFFICE_INTERNAL_URL + ONLYOFFICE_HEALTHCHECK_PATH
```

Ejemplo:

```text
http://localhost:8082/healthcheck
```

La consulta respeta:

- `ONLYOFFICE_REQUEST_TIMEOUT_SECONDS`
- `ONLYOFFICE_VERIFY_SSL`

## Diagnóstico administrativo

Ruta:

```text
/documentacion/integraciones/onlyoffice/
```

Requiere:

- sesión iniciada;
- permiso `documentos.ver_historial`.

La página muestra URLs, estado de health check e instrucciones de ping. No muestra `ONLYOFFICE_JWT_SECRET`.

## Ping técnico de conectividad

Endpoint:

```text
POST /documentacion/integraciones/onlyoffice/ping
```

Protección:

- JWT HS256 firmado con `ONLYOFFICE_JWT_SECRET`;
- issuer y audience configurados por LabZenISO;
- expiración corta;
- scope `onlyoffice:ping`.

Ejemplo conceptual:

```bash
curl -X POST "http://host.docker.internal:5000/documentacion/integraciones/onlyoffice/ping" \
  -H "Authorization: Bearer <TOKEN_GENERADO_EN_DIAGNOSTICO>" \
  -H "Content-Type: application/json" \
  -d "{}"
```

El endpoint:

- no acepta archivos;
- no modifica documentos;
- no modifica base de datos;
- no crea versiones;
- no procesa guardados;
- queda deshabilitado si `ONLYOFFICE_ENABLED=false`.

## Prueba desde el contenedor

Con ONLYOFFICE levantado y LabZenISO corriendo en Windows:

```bash
docker compose -f docker-compose.onlyoffice.yml exec onlyoffice-document-server \
  curl -X POST "http://host.docker.internal:5000/documentacion/integraciones/onlyoffice/ping" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{}"
```

Si Windows Firewall bloquea la conexión, no desactivar el firewall globalmente. Crear solo una regla local limitada al puerto de desarrollo necesario o autorizar manualmente Python/Flask para la red local.

## Seguridad

Validado en este paquete:

- integración deshabilitada por defecto;
- secretos fuera del código;
- `.env` ignorado;
- DOCX del cliente ignorado por `docs/cliente/*.docx`;
- página administrativa con login y permiso;
- ping protegido con JWT;
- timeout de health check;
- no se exponen secretos en HTML ni JSON;
- no se usa contenido documental;
- no se escribe en storage;
- no se modifica base de datos.

Pendiente para PAQUETE 4C:

- protección SSRF completa para descarga de callbacks de guardado;
- validación de redirects;
- validación de IP privada;
- validación MIME/ZIP del DOCX guardado;
- idempotencia persistente de callbacks.

## Verificar que no se usó el DOCX real

El PAQUETE 4A no requiere abrir ni montar:

```text
docs/cliente/PEE CONDUCTICIDAD ELEC ANHIDRO v1.docx
```

Verificar protección:

```bash
git check-ignore -v "docs/cliente/PEE CONDUCTICIDAD ELEC ANHIDRO v1.docx"
```

Debe devolver la regla:

```text
docs/cliente/*.docx
```

## Solución de errores frecuentes

- `Connection refused`: ONLYOFFICE no está levantado o el puerto no coincide.
- `Timeout`: contenedor no responde o firewall/red bloquea.
- `401 en ping`: JWT ausente, inválido o vencido.
- `404 en ping`: `ONLYOFFICE_ENABLED=false`.
- `host.docker.internal` no resuelve: revisar versión de Docker Desktop o configuración de red.

## Paso hacia PAQUETE 4B

Iniciar PAQUETE 4B solo cuando:

- Docker Compose levante ONLYOFFICE;
- health check responda;
- ping desde contenedor llegue a LabZenISO;
- la página administrativa esté protegida;
- pruebas automatizadas pasen;
- el DOCX real siga ignorado y no haya sido usado.
