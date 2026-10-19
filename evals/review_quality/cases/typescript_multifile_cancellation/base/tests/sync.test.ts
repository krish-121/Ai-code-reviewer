import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Snapshot } from '../app/repository';
import { refresh } from '../app/api';
test('successful reads update an independent local snapshot', async () => {
  const snapshot = new Snapshot();
  const result = await refresh({ read: async ids => ids.map(id => ({ id, value: 'ready' })) }, snapshot, ['a', 'b']);
  assert.deepEqual(result, { count: 2, ids: ['a', 'b'] });
  const copy = snapshot.all(); copy[0].value = 'changed';
  assert.equal(snapshot.all()[0].value, 'ready');
});
test('transport failure never writes a snapshot', async () => {
  const snapshot = new Snapshot();
  await assert.rejects(() => refresh({ read: async () => { throw new Error('offline'); } }, snapshot, ['a']), /offline/);
  assert.equal(snapshot.count(), 0);
});
test('duplicate ids are rejected before transport', async () => {
  let calls = 0;
  await assert.rejects(() => refresh({ read: async () => { calls++; return []; } }, new Snapshot(), ['a', 'a']), /duplicate/);
  assert.equal(calls, 0);
});
