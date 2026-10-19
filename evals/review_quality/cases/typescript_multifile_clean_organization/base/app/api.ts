/** The framework has authenticated the principal before invoking this boundary. */
import { Principal } from './models';
import { InvoiceRepository } from './repository';
import { listInvoices } from './service';
import { serialize } from './response';
export function browse(repository: InvoiceRepository, principal: Principal, limit = 20) {
  return serialize(listInvoices(repository, principal, limit));
}
