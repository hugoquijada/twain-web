# DeviceBridge

Agente local para Windows que permite a una aplicación web autorizada solicitar escaneos y, en una fase posterior, impresiones. El agente escucha solamente en `127.0.0.1`; el navegador nunca obtiene acceso directo a controladores o comandos del sistema.

## Alcance de este repositorio

- `agent/`: API local Python, almacenamiento de trabajos y adaptadores de escáner.
- `examples/javascript/`: cliente JavaScript sin framework para probar la API local.

No incluye un coordinador PHP, un paquete TypeScript ni instalador todavía.

## Estado inicial

La primera entrega contiene la infraestructura de trabajos, SQLite, autorización, configuración YAML, un controlador de escáner simulado y la API `/api/v1`. El adaptador físico WIA/TWAIN y la generación de un ejecutable Windows permanecen pendientes de pruebas en Windows con los controladores HP instalados.

## Desarrollo local

En Windows, desde `agent/`:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
$env:DEVICEBRIDGE_API_TOKEN = "genere-un-secreto-aleatorio"
Copy-Item ..\config.example.yaml config.yaml
.\scripts\run.ps1
```

El archivo de ejemplo inicia en modo simulado para pruebas. Para un dispositivo real, cambie `driver` a `wia` o `twain`; esa selección no quedará operativa hasta que se implemente y valide el adaptador correspondiente.

Los scripts de desarrollo establecen `PYTHONPYCACHEPREFIX` para que el bytecode se guarde bajo `.runtime/pycache/`, fuera de `src/` y `tests/`.
