/** Expose allowed invoice fields and an organization-scoped count. */
import { InvoicePage } from './models';
export function serialize(page: InvoicePage): InvoicePage {
  return { invoices: page.invoices.map(row => ({ ...row })), total: page.total };
}
