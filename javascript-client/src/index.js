export class DeviceBridgeError extends Error {
  constructor(message, { status, code, details } = {}) {
    super(message);
    this.name = 'DeviceBridgeError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class DeviceBridgeClient {
  constructor({ baseUrl = 'http://127.0.0.1:8765/api/v1', token, fetchImplementation = globalThis.fetch } = {}) {
    if (typeof fetchImplementation !== 'function') {
      throw new TypeError('DeviceBridgeClient requiere una implementación de fetch.');
    }
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.token = token;
    this.fetch = fetchImplementation.bind(globalThis);
  }

  health() {
    return this.#json('/health');
  }

  version() {
    return this.#json('/version');
  }

  listScanners() {
    return this.#json('/scanners');
  }

  detectScanners() {
    return this.#json('/scanners/detected');
  }

  getScannerCapabilities(scannerId) {
    return this.#json(`/scanners/${encodeURIComponent(scannerId)}/capabilities`);
  }

  createScan(request, { idempotencyKey = crypto.randomUUID() } = {}) {
    return this.#json('/scans', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey
      },
      body: JSON.stringify(request)
    });
  }

  getScan(jobId) {
    return this.#json(`/scans/${encodeURIComponent(jobId)}`);
  }

  cancelScan(jobId) {
    return this.#json(`/scans/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
  }

  listJobs() {
    return this.#json('/jobs');
  }

  async deleteJob(jobId) {
    await this.#request(`/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
  }

  async waitForScan(jobId, { intervalMs = 500, signal } = {}) {
    for (;;) {
      if (signal?.aborted) {
        throw new DOMException('La espera del escaneo fue cancelada.', 'AbortError');
      }
      const job = await this.getScan(jobId);
      if (job.state === 'COMPLETED') {
        return job;
      }
      if (['FAILED', 'CANCELLED', 'TIMEOUT', 'UNCERTAIN'].includes(job.state)) {
        throw new DeviceBridgeError(job.error?.message || `El trabajo terminó en ${job.state}.`, {
          code: job.error?.code || job.state,
          details: job
        });
      }
      await delay(intervalMs, signal);
    }
  }

  async downloadScan(jobId) {
    return this.#request(`/scans/${encodeURIComponent(jobId)}/file`).then((response) => response.blob());
  }

  listVirtualHereDevices() {
    return this.#json('/virtualhere/devices');
  }

  getVirtualHereDevice(deviceId) {
    return this.#json(`/virtualhere/devices/${encodeURIComponent(deviceId)}`);
  }

  connectVirtualHereDevice(deviceId) {
    return this.#json(`/virtualhere/devices/${encodeURIComponent(deviceId)}/connect`, { method: 'POST' });
  }

  disconnectVirtualHereDevice(deviceId) {
    return this.#json(`/virtualhere/devices/${encodeURIComponent(deviceId)}/disconnect`, { method: 'POST' });
  }

  async #json(path, options) {
    const response = await this.#request(path, options);
    return response.json();
  }

  async #request(path, options = {}) {
    const headers = new Headers(options.headers);
    if (this.token) {
      headers.set('Authorization', `Bearer ${this.token}`);
    }
    const response = await this.fetch(`${this.baseUrl}${path}`, { ...options, headers });
    if (!response.ok) {
      let body = {};
      try {
        body = await response.json();
      } catch {
        // A non-JSON failure must still be surfaced as a stable library error.
      }
      const error = body.detail || body;
      throw new DeviceBridgeError(error.message || `Error HTTP ${response.status}.`, {
        status: response.status,
        code: error.code,
        details: error
      });
    }
    return response;
  }
}

function delay(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(resolve, milliseconds);
    signal?.addEventListener('abort', () => {
      clearTimeout(timeout);
      reject(new DOMException('La espera del escaneo fue cancelada.', 'AbortError'));
    }, { once: true });
  });
}
