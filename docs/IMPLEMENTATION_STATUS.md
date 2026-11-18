# Estado de implementación

## Implementado para desarrollo

- API local versionada bajo `/api/v1` para salud, versión, inventario, capacidades y trabajos de escaneo.
- Validación de `config.yaml`: enlace exclusivo a `127.0.0.1`, lista explícita de orígenes y secreto tomado de una variable de entorno.
- Validación de `Host`, `Origin` y encabezado `Authorization: Bearer`; CORS sin comodín.
- Trabajos con UUID, clave de idempotencia y estado persistido en SQLite.
- Archivos temporales aleatorizados por UUID de trabajo.
- Adaptador simulado, útil para probar la API y el ejemplo JavaScript sin hardware.

## Pendiente y no certificado

- Vinculación por instalación, revocación y almacenamiento protegido de credenciales. El token actual es una protección de desarrollo tomada de una variable de entorno; no se presenta como mecanismo de vinculación de producción.
- `WiaScannerDriver` para HP LaserJet Pro MFP 4103fdw.
- `TwainScannerDriver` para HP Color LaserJet Pro MFP 3303fdw y como respaldo de la 4103fdw.
- Enumeración real de dispositivos, capacidades, ADF, dúplex, multipágina, JPEG/PDF y errores del controlador.
- Rotación/expiración de archivos, cancelación, impresión, empaquetado e instalador Windows.

Los adaptadores reales se implementarán solamente contra una computadora Windows de prueba con el controlador HP correspondiente instalado. No se debe cambiar un escáner a `wia` o `twain` en producción esperando que el marcador actual capture documentos: devuelve `SCANNER_DRIVER_UNAVAILABLE` de forma explícita.
