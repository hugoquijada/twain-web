# DeviceBridge

Agente local para Windows que permite a una aplicación web autorizada solicitar escaneos y, en una fase posterior, impresiones. El agente escucha solamente en `127.0.0.1`; el navegador nunca obtiene acceso directo a controladores o comandos del sistema.

## Alcance de este repositorio

- `agent/`: API local Python, almacenamiento de trabajos y adaptadores de escáner.
- `examples/javascript/`: cliente JavaScript sin framework para probar la API local.

No incluye un coordinador PHP ni un paquete TypeScript. Para Windows x64 se genera un instalador de Puente Escáner.

## Estado inicial

La primera entrega contiene la infraestructura de trabajos, SQLite, autorización, configuración YAML, un controlador de escáner simulado y la API `/api/v1`. El adaptador TWAIN ya fue probado con un Brother DSmobile DS-740D; la validación de WIA y de los modelos HP sigue pendiente en Windows.

## Desarrollo local

Use Python 3.11 a 3.14. Python 3.15 todavía puede provocar instalaciones desde código fuente de dependencias como PyYAML, en lugar de usar ruedas compatibles.

En Windows, las integraciones TWAIN de `naps2-scan` requieren **.NET Runtime 8 x64 o superior**. No es necesario instalar el SDK de .NET para ejecutar el agente.

El instalador de Puente Escáner incluye .NET Runtime 8 x64 y lo instala silenciosamente solo si el equipo aún no dispone de .NET 8 o una versión posterior. También registra Puente Escáner para que se inicie automáticamente al iniciar sesión en Windows.

En Windows, desde `agent/`:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
$env:DEVICEBRIDGE_API_TOKEN = "genere-un-secreto-aleatorio"
Copy-Item ..\config.example.yaml config.yaml
.\scripts\run.ps1
```

Si un controlador bloquea el agente durante un escaneo, deténgalo desde otra ventana de PowerShell con:

```powershell
.\scripts\stop.ps1
```

El archivo de ejemplo inicia en modo simulado para pruebas. Para un dispositivo real, cambie `driver` a `wia` o `twain`; esa selección no quedará operativa hasta que se implemente y valide el adaptador correspondiente.

Los scripts de desarrollo establecen `PYTHONPYCACHEPREFIX` para que el bytecode se guarde bajo `.runtime/pycache/`, fuera de `src/` y `tests/`.

En Windows, el arranque normal muestra el icono verde de DeviceBridge en la bandeja del sistema. Desde **Configurar escáner…** se detectan fuentes WIA/TWAIN y se pueden establecer los valores predeterminados de fuente, color, resolución, formato y dúplex.

Los perfiles de escáner ya no se administran en `config.yaml`: se guardan en `devicebridge.sqlite3` dentro del directorio de datos del agente. El icono de la bandeja abre el portal local, donde se detecta una fuente TWAIN/WIA y se crea el perfil. El enlace incluye una sesión administrativa temporal y solo funciona en `127.0.0.1`.

## Empaquetado para instalación

En Windows x64, con el entorno de desarrollo instalado, ejecute desde `agent/`:

```powershell
.\scripts\build-installer.ps1
```

El comando crea `dist\installer\PuenteEscaner-Setup.exe`. Si el instalador de .NET Runtime no está presente, el script descarga la versión oficial fijada durante la compilación. El archivo se ignora en Git porque es un binario redistribuible.

## Servir el ejemplo JavaScript

El ejemplo importa la librería local `javascript-client/`, por lo que el servidor HTTP debe iniciarse desde la raíz de DeviceBridge, no desde `examples/javascript/`:

```powershell
cd C:\ruta\devicebridge
python -m http.server 8080 --bind 127.0.0.1
```

Abra `http://127.0.0.1:8080/examples/javascript/`.
