/** Expose allowed invoice fields and an organization-scoped count. */
import { InvoicePage } from './models';
export function serialize(page: InvoicePage): InvoicePage {
  const invoices = page.invoices.map(row => ({ ...row }));
  return { invoices, total: page.total };
}
