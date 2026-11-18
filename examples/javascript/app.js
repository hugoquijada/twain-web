import { DeviceBridgeClient } from '../../javascript-client/src/index.js';

const controls = {
  token: document.querySelector('#token'),
  load: document.querySelector('#load'),
  scanner: document.querySelector('#scanner'),
  scan: document.querySelector('#scan'),
  status: document.querySelector('#status'),
  preview: document.querySelector('#preview')
};

function setStatus(value) {
  controls.status.textContent = value;
}

function bridge() {
  return new DeviceBridgeClient({ token: controls.token.value });
}

controls.load.addEventListener('click', async () => {
  try {
    const { items } = await bridge().listScanners();
    controls.scanner.replaceChildren(...items.map((item) => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.name;
      return option;
    }));
    controls.scanner.disabled = items.length === 0;
    controls.scan.disabled = items.length === 0;
    setStatus(`${items.length} escáner(es) configurado(s).`);
  } catch (error) {
    setStatus(`No fue posible detectar el agente: ${error.message}`);
  }
});

controls.scan.addEventListener('click', async () => {
  controls.scan.disabled = true;
  try {
    const job = await bridge().createScan({
      scanner_id: controls.scanner.value,
      source: 'adf',
      color_mode: 'color',
      resolution: 300,
      output_format: 'png',
      duplex: false
    });
    await waitForCompletion(job.id);
  } catch (error) {
    setStatus(`No fue posible iniciar el escaneo: ${error.message}`);
  } finally {
    controls.scan.disabled = false;
  }
});

async function waitForCompletion(jobId) {
  for (;;) {
    const job = await bridge().getScan(jobId);
    setStatus(`Trabajo ${job.id}: ${job.state}`);
    if (job.state === 'COMPLETED') {
      const blob = await bridge().downloadScan(job.id);
      controls.preview.src = URL.createObjectURL(blob);
      controls.preview.hidden = false;
      return;
    }
    if (['FAILED', 'CANCELLED', 'TIMEOUT', 'UNCERTAIN'].includes(job.state)) {
      throw new Error(job.error?.message || job.state);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
}
