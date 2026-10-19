const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Catalog } = require('../app/repository');
const { item } = require('../app/models');
const { browse } = require('../app/api');
test('three public pages have no duplicates or missing rows', () => {
  const catalog = new Catalog(Array.from({ length: 7 }, (_, n) => item(n + 1, `item ${n + 1}`)));
  const pages = [0, 1, 2].map(page => browse(catalog, { page, size: 3 }));
  assert.deepEqual(pages.flatMap(result => result.items.map(row => row.id)), [1, 2, 3, 4, 5, 6, 7]);
  assert.equal(pages[2].hasMore, false);
  assert.deepEqual(browse(catalog, { page: 4, size: 3 }).items, []);
});
