# Checklist funcional del módulo documental

Validar estos escenarios en la rama funcional del módulo documental, usando usuarios con roles `TECNICO`, `CALIDAD`/`ADMINISTRADOR` y `CONSULTA`.

## Escenarios principales

1. Ingresar como usuario técnico.
2. Crear un documento nuevo desde Gestión Documental.
3. Confirmar que el documento queda en estado `BORRADOR`.
4. Enviar el documento a revisión.
5. Confirmar que el documento cambia a `EN_REVISION`.
6. Ingresar como usuario `CALIDAD` o `ADMINISTRADOR`.
7. Confirmar que aparece la alerta visual de pendientes.
8. Entrar a `/documentacion/pendientes`.
9. Confirmar que el documento enviado aparece en la bandeja.
10. Intentar aprobar como `TECNICO` y confirmar que no está permitido.
11. Aprobar el documento como `CALIDAD` o `ADMINISTRADOR`.
12. Confirmar que el documento queda `APROBADO`.
13. Confirmar que existe una versión vigente.
14. Crear una nueva versión sobre el documento aprobado.
15. Confirmar el estado funcional `EN ACTUALIZACIÓN`.
16. Enviar la nueva versión a revisión.
17. Rechazar la nueva versión con comentario obligatorio.
18. Confirmar que el comentario de rechazo queda visible en la trazabilidad.
19. Devolver la versión rechazada a borrador con comentario.
20. Enviar nuevamente a revisión.
21. Aprobar la nueva versión.
22. Confirmar que la versión anterior queda `SUSTITUIDA`.
23. Confirmar que la nueva versión queda como vigente.
24. Obsoletar el documento con motivo obligatorio.
25. Confirmar que el documento queda `OBSOLETO`.
26. Confirmar que el documento aparece en Archivo Documental.
27. Revisar el historial de versiones.
28. Revisar la traza de eventos del workflow.
29. Descargar una versión con usuario autorizado.
30. Validar que un usuario `CONSULTA` solo puede ver y descargar.
31. Validar que `CONSULTA` no puede crear, editar, aprobar, rechazar ni obsoletar.
32. Validar que usuarios de otra empresa no ven documentos ajenos.
33. Entrar a `/documentacion/dashboard`.
34. Confirmar conteos por estado documental.
35. Confirmar conteo de `VIGENTE`.
36. Confirmar conteo de `EN ACTUALIZACIÓN`.
37. Confirmar conteo por tipo documental.
38. Confirmar lista de pendientes recientes.
39. Confirmar documentos recientes.
40. Confirmar documentos obsoletos recientes.

## Criterio de aceptación funcional

El flujo queda aprobado si el ciclo completo creación → revisión → aprobación → nueva versión → sustitución → obsolescencia conserva trazabilidad, permisos, descarga protegida y aislamiento por empresa.
