import { test } from 'node:test';
import assert from 'node:assert/strict';
import { InvoiceRepository } from '../app/repository';
import { browse } from '../app/api';
test('a single organization can browse its invoices', () => {
  const repository = new InvoiceRepository([{ id: 'i1', organizationId: 'a', amountMinor: 100 }]);
  const result = browse(repository, { id: 'u1', organizationId: 'a' });
  assert.deepEqual(result.invoices.map(row => row.id), ['i1']);
  assert.equal(result.total, 1);
});
test('page size and organization are validated', () => {
  assert.throws(() => browse(new InvoiceRepository([]), { id: 'u1', organizationId: '' }));
  assert.throws(() => browse(new InvoiceRepository([]), { id: 'u1', organizationId: 'a' }, 0));
});
test('returned invoices do not expose stored objects', () => {
  const repository = new InvoiceRepository([{ id: 'i1', organizationId: 'a', amountMinor: 100 }]);
  const principal = { id: 'u1', organizationId: 'a' };
  browse(repository, principal).invoices[0].amountMinor = 0;
  assert.equal(browse(repository, principal).invoices[0].amountMinor, 100);
});
