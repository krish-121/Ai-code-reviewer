/** Use the authenticated principal's organization for both data and total count. */
import { Principal, InvoicePage } from './models';
import { InvoiceRepository } from './repository';
import { organization, pageSize } from './validation';
export function listInvoices(repository: InvoiceRepository, principal: Principal, limit: number): InvoicePage {
  return repository.list(organization(principal.organizationId), pageSize(limit));
}
