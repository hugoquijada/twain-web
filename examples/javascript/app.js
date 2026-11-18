const bridgeUrl = 'http://127.0.0.1:8765/api/v1';
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

async function request(path, options = {}) {
  const response = await fetch(`${bridgeUrl}${path}`, {
    ...options,
    headers: {
      ...(controls.token.value ? { Authorization: `Bearer ${controls.token.value}` } : {}),
      ...options.headers
    }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = body.detail || body;
    throw new Error(error.message || `Error HTTP ${response.status}`);
  }
  return response;
}

controls.load.addEventListener('click', async () => {
  try {
    const response = await request('/scanners');
    const { items } = await response.json();
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
  try {
    const response = await request('/scans', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': crypto.randomUUID()
      },
      body: JSON.stringify({
        scanner_id: controls.scanner.value,
        source: 'adf',
        color_mode: 'color',
        resolution: 300,
        output_format: 'png',
        duplex: false
      })
    });
    const job = await response.json();
    await waitForCompletion(job.id);
  } catch (error) {
    setStatus(`No fue posible iniciar el escaneo: ${error.message}`);
  }
});

async function waitForCompletion(jobId) {
  for (;;) {
    const response = await request(`/scans/${jobId}`);
    const job = await response.json();
    setStatus(`Trabajo ${job.id}: ${job.state}`);
    if (job.state === 'COMPLETED') {
      const file = await request(`/scans/${job.id}/file`);
      const blob = await file.blob();
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
