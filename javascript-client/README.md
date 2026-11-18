# @devicebridge/client

Cliente JavaScript ESM sin dependencia de React, Vue o rutas de negocio. La aplicación web conserva su autenticación y solo usa esta librería para hablar con el agente local autorizado.

```js
import { DeviceBridgeClient } from '@devicebridge/client';

const bridge = new DeviceBridgeClient({ token: session.deviceBridgeToken });
const { items } = await bridge.listScanners();
const job = await bridge.createScan({ scanner_id: items[0].id });
await bridge.waitForScan(job.id);
const file = await bridge.downloadScan(job.id);
```

Métodos disponibles: salud, versión, escáneres, capacidades, creación/consulta/espera/descarga de escaneo y control limitado de dispositivos VirtualHere.
