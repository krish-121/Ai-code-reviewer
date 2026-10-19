/** Organization identity is trusted application context, never a query parameter. */
export interface Principal { id: string; organizationId: string }
export interface Invoice { id: string; organizationId: string; amountMinor: number }
export interface InvoicePage { invoices: Invoice[]; total: number }
