/** Use trusted principal context when serving organization invoices. */
import { Principal, InvoicePage } from './models';
import { InvoiceRepository } from './repository';
import { organization, pageSize } from './validation';
export function listInvoices(repository: InvoiceRepository, principal: Principal, limit: number): InvoicePage {
  const organizationId = organization(principal.organizationId);
  return repository.list({ organizationId, limit: pageSize(limit) });
}
