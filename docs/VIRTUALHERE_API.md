# API VirtualHere

La configuración declara cada dispositivo con un identificador lógico y su dirección VirtualHere. La API no recibe comandos ni direcciones del navegador.

- `GET /api/v1/virtualhere/devices`: estados de los dispositivos configurados.
- `GET /api/v1/virtualhere/devices/{id}`: estado actual de un dispositivo.
- `POST /api/v1/virtualhere/devices/{id}/connect`: solicita `USE,<address>`.
- `POST /api/v1/virtualhere/devices/{id}/disconnect`: solicita `STOP USING,<address>` únicamente si la conexión fue creada por este proceso y el estado se confirma como local.

Un reinicio olvida intencionalmente la propiedad de conexiones anteriores. En ese caso la desconexión responde `DEVICE_NOT_OWNED_BY_AGENT`; esto evita cortar una conexión manual o ajena.

Los estados `UNKNOWN` y `CONNECTION_STATE_UNCERTAIN` bloquean la desconexión. Se deberá capturar una salida real de `DEVICE INFO,<address>` en Windows para afinar el parser sin reducir esa protección.

Una conexión que VirtualHere acepte pero cuyo estado no pueda clasificarse responde `connectionAccepted: true` y `safeToDisconnect: false`. Es posible continuar la verificación manual en Windows, pero el agente no la liberará automáticamente.
