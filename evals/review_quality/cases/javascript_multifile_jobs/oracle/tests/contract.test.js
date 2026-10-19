const { test } = require('node:test');
const assert = require('node:assert/strict');
const { job } = require('../app/job');
const { JobRepository } = require('../app/repository');
const { submit } = require('../app/api');
test('mixed batch rejection reaches the API caller', async () => {
  const repository = new JobRepository();
  await assert.rejects(() => submit([job('a', 1), job('b', 2)], async n => {
    if (n === 2) throw new Error('storage unavailable');
    return n * 2;
  }, repository), /storage unavailable/);
  assert.equal(repository.get('a').state, 'complete');
  assert.equal(repository.get('b').state, 'failed');
});
test('an entirely failed batch cannot look like an empty success', async () => {
  await assert.rejects(() => submit([job('a', 1)], async () => {
    throw new Error('offline');
  }, new JobRepository()), /offline/);
});
