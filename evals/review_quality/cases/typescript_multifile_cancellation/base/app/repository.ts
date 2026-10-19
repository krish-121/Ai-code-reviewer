/** Copy completed transport rows into the local snapshot only after a read succeeds. */
import { Row } from './models';
export class Snapshot {
  private rows = new Map<string, Row>();
  putAll(rows: Row[]): void {
    for (const row of rows) this.rows.set(row.id, { ...row });
  }
  all(): Row[] { return [...this.rows.values()].map(row => ({ ...row })); }
  count(): number { return this.rows.size; }
}
