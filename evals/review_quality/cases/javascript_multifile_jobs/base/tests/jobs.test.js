const { test } = require('node:test');
const assert = require('node:assert/strict');
const { job } = require('../app/job');
const { JobRepository } = require('../app/repository');
const { submit } = require('../app/api');
const { perform } = require('../app/worker');

test('successful jobs are returned in request order', async () => {
  const repository = new JobRepository();
  const response = await submit([job('a', 2), job('b', 3)], async n => n * 2, repository);
  assert.deepEqual(response, { count: 2, ids: ['a', 'b'], values: [4, 6] });
  assert.equal(repository.completedCount(), 2);
});
test('empty batches succeed', async () => {
  assert.equal((await submit([], async n => n, new JobRepository())).count, 0);
});
test('one worker records and propagates failure', async () => {
  const repository = new JobRepository();
  await assert.rejects(() => perform(job('a', 1), async () => { throw new Error('offline'); }, repository), /offline/);
  assert.equal(repository.get('a').state, 'failed');
});
test('job identifiers are required', () => { assert.throws(() => job('', 1)); });
