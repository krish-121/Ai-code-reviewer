/** Use trusted principal context when serving organization invoices. */
import { Principal, InvoicePage } from './models';
import { InvoiceRepository } from './repository';
import { organization, pageSize } from './validation';
export function listInvoices(repository: InvoiceRepository, principal: Principal, limit: number): InvoicePage {
  organization(principal.organizationId);
  return repository.list({ limit: pageSize(limit) });
}
