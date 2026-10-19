const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Catalog } = require('../app/repository');
const { item } = require('../app/models');
const { browse } = require('../app/api');
test('first page includes sorted items', () => {
  const catalog = new Catalog([item(3, 'c'), item(1, 'a'), item(2, 'b')]);
  const result = browse(catalog, { page: 0, size: 2 });
  assert.deepEqual(result.items.map(row => row.id), [1, 2]);
  assert.equal(result.hasMore, true);
});
test('empty catalog has no next page', () => {
  assert.equal(browse(new Catalog([])).hasMore, false);
});
test('invalid page shape is rejected', () => {
  assert.throws(() => browse(new Catalog([]), { page: -1 }));
  assert.throws(() => browse(new Catalog([]), { size: 0 }));
});
test('repository windows use offsets', () => {
  const catalog = new Catalog([item(1, 'a'), item(2, 'b'), item(3, 'c')]);
  assert.deepEqual(catalog.window(1, 1).map(row => row.id), [2]);
});
