import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Snapshot } from '../app/repository';
import { refresh } from '../app/api';
test('pre-aborted cancellation reaches the transport and prevents saving', async () => {
  const controller = new AbortController(); controller.abort();
  const snapshot = new Snapshot();
  const reader = { read: async (_ids, options) => {
    if (options?.signal?.aborted) throw new Error('aborted');
    return [{ id: 'a', value: 'loaded' }];
  }};
  await assert.rejects(() => refresh(reader, snapshot, ['a'], controller.signal), /aborted/);
  assert.equal(snapshot.count(), 0);
});
test('the same signal is forwarded and in-flight rejection reaches the caller', async () => {
  const controller = new AbortController(); const snapshot = new Snapshot();
  let started;
  const ready = new Promise(resolve => { started = resolve; });
  const reader = { read: async (_ids, options) => {
    assert.equal(options?.signal, controller.signal);
    started();
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }));
  }};
  const pending = refresh(reader, snapshot, ['a'], controller.signal);
  // Attach the rejection assertion immediately; a missing signal fails without hanging.
  const rejected = assert.rejects(pending, /aborted/);
  await Promise.race([ready, pending.then(() => undefined, () => undefined)]);
  controller.abort();
  await rejected;
  assert.equal(snapshot.count(), 0);
});
