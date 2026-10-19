/** Each public invoice query is restricted to the supplied organization. */
import { Invoice, InvoicePage } from './models';
export class InvoiceRepository {
  private readonly rows: Invoice[];
  constructor(rows: Invoice[]) { this.rows = rows.map(row => ({ ...row })); }
  list(organizationId: string, limit: number): InvoicePage {
    const selected = this.rows.filter(row => row.organizationId === organizationId);
    return { invoices: selected.slice(0, limit).map(row => ({ ...row })), total: selected.length };
  }
}
