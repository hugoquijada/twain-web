# DeviceBridge: objetivo y plan de continuidad

## Objetivo

DeviceBridge será un agente local instalable en Windows que permita a un sistema web autorizado usar escáneres e impresoras físicamente disponibles en esa computadora. El navegador no hablará directamente con controladores, TWAIN, WIA, VirtualHere ni comandos del sistema: usará una API HTTP local en `127.0.0.1`.

El resultado esperado es un instalador Inno Setup que coloque el agente, lo inicie con el usuario de Windows, muestre un icono de bandeja y permita configurar dispositivos desde un portal local. El usuario final no instalará Python ni editará archivos YAML.

## Alcance actual

Este repositorio contiene solo:

- `agent/`: agente Python que después será empaquetado como ejecutable Windows.
- `javascript-client/`: librería JavaScript ESM sin dependencia de framework.
- `examples/javascript/`: ejemplo web que consume la librería.

No existe coordinador central PHP ni paquete TypeScript. La coordinación entre varias computadoras y la impresión completa se incorporarán después de que funcione un flujo local confiable.

## Principios de diseño

1. El agente escucha exclusivamente en `127.0.0.1`.
2. El sistema web conserva autenticación, expedientes y almacenamiento definitivo de documentos.
3. DeviceBridge conserva trabajos operativos y archivos temporales; no reglas de negocio.
4. Un escáner o impresora se usa mediante un ID lógico local, no mediante nombres TWAIN/WIA o direcciones USB enviados por el navegador.
5. No se ejecutan comandos arbitrarios recibidos por HTTP.
6. No se desconecta un dispositivo VirtualHere si el agente no puede demostrar que la conexión fue creada por él durante la sesión actual.
7. Una prueba simulada, una prueba de API y una prueba física son evidencias distintas.

## Arquitectura objetivo

```text
Aplicación web
  └─ @devicebridge/client
       └─ http://127.0.0.1:8765/api/v1
            └─ DeviceBridge Agent
                 ├─ Registro de trabajos SQLite
                 ├─ Perfiles de dispositivos SQLite
                 ├─ TWAIN / WIA
                 ├─ Windows Print Spooler (pendiente)
                 ├─ VirtualHere (parcial)
                 └─ Portal local de administración
```

### Configuración

- `config.yaml`: solamente arranque y seguridad del agente: puerto, directorios, orígenes permitidos, nivel de diagnóstico y VirtualHere.
- `devicebridge.sqlite3`: perfiles persistentes de escáneres creados desde el portal local.
- Una sección `scanners:` antigua de YAML se importa una sola vez si la base de datos no contiene perfiles. No debe usarse para nuevas instalaciones.

## Portal local de administración

El icono de bandeja abre `http://127.0.0.1:<puerto>/admin` con una capacidad administrativa local que se inserta en el fragmento de la URL. No la administra ni copia el usuario, y no se envía al servidor al cargar la página.

El portal debe permitir:

1. Detectar fuentes TWAIN y WIA realmente registradas en Windows.
2. Elegir una fuente detectada y crear un ID lógico.
3. Configurar cristal/bandeja, color, resolución, formato y dúplex.
4. Guardar perfiles en SQLite y aplicarlos sin reiniciar el agente.
5. Consultar disponibilidad y realizar una prueba de escaneo.
6. Posteriormente, administrar impresoras y VirtualHere.

El cliente web de negocio no debe poder agregar fuentes arbitrarias ni editar perfiles.

## Estado real a noviembre de 2026

### Implementado, con verificación estática o simulada

- API local FastAPI, trabajos SQLite, identificadores UUID e idempotencia de escaneo.
- Cliente JavaScript ESM: detección, escaneo, consulta de trabajos, descarga como `Blob` y métodos VirtualHere.
- Detección real de TWAIN y WIA mediante `/api/v1/scanners/detected`.
- Portal local inicial para descubrir y guardar perfiles en SQLite.
- Icono de bandeja de Windows que abre el portal local.
- Adaptadores TWAIN, WIA y VirtualHere con límites de seguridad.
- Pruebas unitarias de SQLite, estados VirtualHere y cliente JavaScript.

### Evidencia física disponible

- Brother DSmobile DS-740D: se consiguió iniciar el flujo TWAIN durante pruebas.
- Windows detectó estas fuentes HP:

  - `TWAIN: HP Color LaserJet Pro M478f-9f TW`
  - `WIA: HP Color LaserJet Pro M478f-9f (NET)`
  - `WIA: HPF64A71 (HP Color LaserJet Pro M478f-9f)`

Esto prueba detección del controlador, no entrega final confiable de imagen ni ADF/multipágina.

### Pendiente y no certificado

- Entrega confiable del archivo después de una captura física TWAIN.
- ADF, cristal, dúplex, varias páginas y PDF multipágina.
- Validación física de HP M479fdw, HP 3303fdw y HP 4103fdw.
- Enumeración e impresión con colas de Windows.
- Supervisión de impresión y periodo seguro antes de liberar USB.
- Empaquetado PyInstaller e instalador Inno Setup.
- Actualización remota firmada.
- Coordinación de dispositivos compartidos entre equipos.

## Hardware y controladores

### Brother DSmobile DS-740D

Escáner USB portátil con alimentador; no tiene cristal. Usar `source: adf`. Es útil para validar TWAIN, pero no representa un ADF de 50 hojas de las HP.

### HP Color LaserJet Pro M478f-9f

Windows reportó la fuente TWAIN exacta `HP Color LaserJet Pro M478f-9f TW`; al crear un perfil local, usar inicialmente TWAIN y ese nombre. Cuenta con cristal y ADF. Probar ambas rutas por separado.

### HP M479fdw, 3303fdw y 4103fdw

Se configurarán desde el portal después de instalar el controlador HP y confirmar primero un escaneo con HP Scan o Escáner de Windows. No asumir nombres: usar la fuente detectada en cada PC.

## API relevante

### Operación web

- `GET /api/v1/health`
- `GET /api/v1/scanners`
- `GET /api/v1/scanners/detected`
- `POST /api/v1/scans`
- `GET /api/v1/scans/{jobId}`
- `GET /api/v1/scans/{jobId}/file`

### Administración local

- `GET /admin`
- `GET /admin/api/scanners`
- `POST /admin/api/scanners`

### VirtualHere parcial

- `GET /api/v1/virtualhere/devices`
- `POST /api/v1/virtualhere/devices/{id}/connect`
- `POST /api/v1/virtualhere/devices/{id}/disconnect`

VirtualHere solo recibe IDs previamente configurados. Todavía no imprime.

## Plan de trabajo recomendado

### Fase A: cerrar escaneo local

1. En Windows, usar el portal para crear el perfil del escáner HP detectado.
2. Confirmar que el portal muestra `detected: true`.
3. Probar una hoja desde cristal a 300 dpi PNG.
4. Confirmar que el trabajo llega a `COMPLETED` y que `/file` devuelve una imagen válida.
5. Corregir cualquier error de conversión, temporal o descarga antes de avanzar.
6. Implementar PDF multipágina real y soporte ADF/dúplex.
7. Agregar pruebas físicas documentadas para Brother y HP.

### Fase B: administración de impresoras

1. Enumerar colas instaladas de Windows.
2. Crear perfiles de impresora en SQLite desde el portal.
3. Conectar USB VirtualHere cuando el perfil lo requiera.
4. Implementar impresión Windows y trabajo de impresión persistente.
5. No afirmar finalización física solo porque desaparece la cola de Windows.

### Fase C: distribución Windows

1. Empaquetar con PyInstaller en Windows x64.
2. Inno Setup instala ejecutable, runtime requerido y accesos de inicio.
3. Instalar .NET Runtime 8 x64, requerido por `naps2-scan`/TWAIN.
4. Guardar datos en `C:\ProgramData\DeviceBridge` y binarios en `Program Files`.
5. Ejecutar el agente por usuario, no como servicio sin interacción: WIA/TWAIN pueden requerir sesión de escritorio.
6. Verificar instalación limpia, bandeja, portal y primer escaneo.

### Fase D: seguridad y mantenimiento

1. Antes de producción, decidir autorización de la API local. Para pruebas puede usarse `authentication_required: false`; no es la política final recomendada para aplicaciones web externas.
2. Mantener CORS explícito y validación de `Host`/`Origin`.
3. Implementar logs rotativos y diagnósticos sin contenido de documentos.
4. Diseñar actualización remota mediante instaladores firmados y manifiestos verificables.

## Preparación del equipo Windows

1. Python 3.11–3.14 para desarrollo; no usar Python 3.15 actualmente.
2. Crear venv e instalar `pip install -e ".[dev]"`.
3. Instalar .NET Runtime 8 x64 o superior para `naps2-scan`.
4. Instalar controlador completo del fabricante, incluyendo WIA/TWAIN.
5. Comprobar primero el escáner con HP Scan, Brother iPrint&Scan o Escáner de Windows.
6. Iniciar el agente y abrir la configuración desde la bandeja.

## Criterio para avanzar

No avanzar a impresión, instalador o coordinación multiusuario hasta poder demostrar en Windows que un escáner seleccionado en el portal captura una página, el agente persiste el archivo temporal, el cliente lo descarga como `Blob` y el navegador lo muestra correctamente.
