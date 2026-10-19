import { test } from 'node:test';
import assert from 'node:assert/strict';
import { InvoiceRepository } from '../app/repository';
import { browse } from '../app/api';
const rows = [{ id: 'private-b', organizationId: 'b', amountMinor: 99999 },
              { id: 'mine-a', organizationId: 'a', amountMinor: 100 }];
test('another organization invoice and count never enter the API response', () => {
  const repository = new InvoiceRepository(rows);
  const result = browse(repository, { id: 'u1', organizationId: 'a' }, 1);
  assert.deepEqual(result.invoices.map(row => row.id), ['mine-a']);
  assert.equal(result.total, 1);
});
test('an organization with no rows receives no data or counts', () => {
  const result = browse(new InvoiceRepository(rows), { id: 'u2', organizationId: 'c' });
  assert.deepEqual(result, { invoices: [], total: 0 });
});
