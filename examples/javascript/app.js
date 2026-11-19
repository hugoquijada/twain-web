import { DeviceBridgeClient } from '../../javascript-client/src/index.js';

const controls = {
  token: document.querySelector('#token'),
  load: document.querySelector('#load'),
  scanner: document.querySelector('#scanner'),
  scan: document.querySelector('#scan'),
  cancel: document.querySelector('#cancel'),
  status: document.querySelector('#status'),
  preview: document.querySelector('#preview')
};

let activeJobId = null;

function setStatus(value) {
  controls.status.textContent = value;
}

function bridge() {
  return new DeviceBridgeClient({ token: controls.token.value });
}

controls.load.addEventListener('click', async () => {
  try {
    const [{ items }, detection] = await Promise.all([
      bridge().listScanners(),
      bridge().detectScanners()
    ]);
    const detectedById = new Map(detection.configured.map((item) => [item.id, item]));
    const available = items.filter((item) => detectedById.get(item.id)?.detected);
    controls.scanner.replaceChildren(...available.map((item) => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.name;
      return option;
    }));
    controls.scanner.disabled = available.length === 0;
    controls.scan.disabled = available.length === 0;
    const unavailable = items.filter((item) => !detectedById.get(item.id)?.detected);
    const diagnostics = detection.diagnostics.length ? ` ${detection.diagnostics.join(' | ')}` : '';
    setStatus(`${available.length} escáner(es) detectado(s).` +
      (unavailable.length ? ` No disponibles: ${unavailable.map((item) => item.name).join(', ')}.` : '') + diagnostics);
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
    activeJobId = job.id;
    controls.cancel.disabled = false;
    await waitForCompletion(job.id);
  } catch (error) {
    setStatus(`No fue posible iniciar el escaneo: ${error.message}`);
  } finally {
    activeJobId = null;
    controls.cancel.disabled = true;
    controls.scan.disabled = false;
  }
});

controls.cancel.addEventListener('click', async () => {
  if (!activeJobId) {
    return;
  }
  controls.cancel.disabled = true;
  try {
    const job = await bridge().cancelScan(activeJobId);
    setStatus(`Trabajo ${job.id}: ${job.state}.`);
  } catch (error) {
    setStatus(`No fue posible cancelar el trabajo: ${error.message}`);
    controls.cancel.disabled = false;
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
