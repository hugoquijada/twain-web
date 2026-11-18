import assert from 'node:assert/strict';
import test from 'node:test';

import { DeviceBridgeClient, DeviceBridgeError } from '../src/index.js';

test('sends the token and creates an idempotent scan request', async () => {
  let captured;
  const client = new DeviceBridgeClient({
    token: 'local-secret',
    fetchImplementation: async (url, options) => {
      captured = { url, options };
      return Response.json({ id: 'job-1', state: 'QUEUED' }, { status: 202 });
    }
  });

  const job = await client.createScan({ scanner_id: 'brother' }, { idempotencyKey: 'request-1' });

  assert.equal(job.id, 'job-1');
  assert.equal(captured.options.headers.get('Authorization'), 'Bearer local-secret');
  assert.equal(captured.options.headers.get('Idempotency-Key'), 'request-1');
});

test('converts the agent error contract into DeviceBridgeError', async () => {
  const client = new DeviceBridgeClient({
    fetchImplementation: async () => Response.json({ detail: { code: 'SCANNER_NOT_FOUND', message: 'No encontrado.' } }, { status: 404 })
  });

  await assert.rejects(client.getScannerCapabilities('missing'), (error) => {
    assert.ok(error instanceof DeviceBridgeError);
    assert.equal(error.status, 404);
    assert.equal(error.code, 'SCANNER_NOT_FOUND');
    return true;
  });
});

test('requests actual scanner detection separately from configured scanners', async () => {
  let requestedUrl;
  const client = new DeviceBridgeClient({
    fetchImplementation: async (url) => {
      requestedUrl = url;
      return Response.json({ devices: [], configured: [], diagnostics: [] });
    }
  });

  await client.detectScanners();
  assert.match(requestedUrl, /\/scanners\/detected$/);
});
