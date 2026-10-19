/** Options-based invoice retrieval, reusable by organization-aware callers. */
import { Invoice, InvoicePage } from './models';
export interface ListOptions { organizationId: string; limit: number }
export class InvoiceRepository {
  private readonly rows: Invoice[];
  constructor(rows: Invoice[]) { this.rows = rows.map(row => ({ ...row })); }
  list(options: ListOptions): InvoicePage {
    const selected = this.rows.filter(row => row.organizationId === options.organizationId);
    return { invoices: selected.slice(0, options.limit).map(row => ({ ...row })), total: selected.length };
  }
}
