# Paquete 4F-A/B/C — Firma externa controlada

Este paquete implementa el flujo de firma externa controlada sobre el `PDF_APROBADO` generado en 4E. LabZenISO no firma documentos por el usuario: entrega el PDF, recibe el PDF firmado fuera de la plataforma y lo valida antes de conservarlo como artefacto privado e inmutable.

El documento permanece `APROBADO`. Este paquete no pasa documentos a `VIGENTE` y no modifica `version_vigente_id`.

## Validador seleccionado

- Librería: `pyHanko`
- Versión fijada: `pyHanko==0.35.2`
- Licencia: MIT
- Compatibilidad: Python >= 3.10; el entorno local validado usa Python 3.11.7 en Windows.
- Motivo: pyHanko expone APIs primarias para enumerar firmas embebidas (`PdfFileReader.embedded_signatures`), validar firmas PDF/CMS/PAdES (`validate_pdf_signature`) y validar cadena de confianza mediante `pyhanko_certvalidator.ValidationContext`.

En producción pyHanko se usa solo para leer y validar firmas/certificados/revisiones. La capacidad de firma de pyHanko está limitada a tests y fixtures sintéticos efímeros.

## Contrato del adaptador

`PyHankoPdfSignatureValidator` devuelve `SignatureValidationResult`, una estructura independiente de pyHanko con:

- estado normalizado (`VALIDA`, `NO_CONFIABLE`, `IDENTIDAD_NO_COINCIDE`, etc.);
- integridad, confianza, identidad y vigencia;
- conteo de firmas nuevas y acumuladas;
- metadatos públicos del certificado;
- nivel de modificación;
- errores sanitizados.

`ExternalControlledSignatureProvider` consume ese adaptador. Las rutas web no llaman pyHanko directamente.

## Trust store

Configuración:

```env
DOCUMENT_SIGNATURES_ENABLED=false
DOCUMENT_SIGNATURE_PROVIDER=external_controlled
DOCUMENT_SIGNATURE_VALIDATION_MODE=strict
DOCUMENT_SIGNATURE_TRUST_ROOTS_PATH=
DOCUMENT_SIGNATURE_ALLOWED_ISSUERS_PATH=
DOCUMENT_SIGNATURE_PROCESS_TTL_DAYS=15
DOCUMENT_SIGNATURE_MAX_PDF_BYTES=52428800
DOCUMENT_SIGNATURE_REVOCATION_MODE=soft-fail
```

Reglas:

- una ruta vacía o inexistente bloquea validación en modo estricto;
- se cargan certificados públicos PEM/DER desde archivo o directorio;
- no se confía automáticamente en certificados incluidos en el PDF;
- no se usan raíces del sistema sin política explícita;
- no se descargan raíces desde Internet;
- no se versionan certificados reales, claves, P12 ni PFX.

Material local excluido por `.gitignore`:

- `instance/signature-trust/`
- `instance/signature-test/`
- `storage/signature-test/`

## Identidad del firmante

La coincidencia es tenant-aware y determinista. Si existe fingerprint SHA-256 autorizado, es autoritativo: si no coincide, se rechaza. Si no existe fingerprint, el servicio puede comparar identificador oficial en subject, serial+issuer, correo del certificado o subject DN exacto configurado en `metadata_json`.

Solo se persisten datos públicos del certificado.

## Secuencia

- Paso 1: entrada con 0 firmas, salida con 1 firma del elaborador.
- Paso 2: entrada con 1 firma válida, salida con 2 firmas y la primera sigue válida.
- Paso 3: entrada con 2 firmas válidas, salida con 3 firmas y las anteriores siguen válidas.

Se rechaza orden incorrecto, más de una firma nueva, firma duplicada, trust store inválido e identidad que no coincide. Si la validación falla, no se crea artefacto firmado y el paso queda `HABILITADO` para corregir la carga.

## Modificaciones e incremental updates

pyHanko ejecuta análisis de diferencias con su política por defecto. El servicio registra `modification_level` normalizado y no declara equivalencia visual usando tamaño, hash o conteo de páginas. Los PDFs firmados pueden contener `/AcroForm` por campos de firma, pero se siguen rechazando cifrado, JavaScript, acciones automáticas y adjuntos.

## Tests criptográficos

Los tests generan en directorio temporal:

- CA raíz de prueba;
- certificados efímeros de elaborador, revisor y aprobador;
- claves privadas efímeras;
- PDF sintético no confidencial.

La prueba real firma incrementalmente 1/3, 2/3 y 3/3 con pyHanko solo dentro de pytest, valida con el proveedor productivo `external_controlled`, conserva `PDF_FIRMADO_PARCIAL` y termina con `PDF_FIRMADO_FINAL`.

Las claves de prueba no se versionan ni se conservan fuera del temporal de pytest.

## Checklist piloto FirmaEC

Estado del piloto humano: `PENDIENTE`.

1. Descargar PDF desde LabZenISO.
2. Firmar con FirmaEC usando certificado real del elaborador.
3. No certificar/bloquear el documento si debe recibir firmas posteriores.
4. Cargar el PDF firmado.
5. Verificar identidad, emisor, confianza e incremental update.
6. Confirmar habilitación del revisor.
7. Repetir para revisor y aprobador.
8. Confirmar `PDF_FIRMADO_FINAL`.

## Checklist piloto Adobe Acrobat

Estado del piloto humano: `PENDIENTE`.

1. Descargar PDF desde LabZenISO.
2. Firmar con certificado digital del usuario en Adobe Acrobat.
3. Evitar opciones que bloqueen firmas posteriores.
4. Cargar el PDF firmado.
5. Validar cadena, identidad, orden y revisiones.
6. Repetir con tres personas distintas.

## Limitaciones

- Revocación OCSP/CRL depende de política y datos disponibles; por defecto `soft-fail` no descarga datos externos.
- La aceptación productiva requiere piloto humano con certificados reales del cliente.
- 4F completo no implica vigencia documental; 4G debe decidir la transición posterior.
