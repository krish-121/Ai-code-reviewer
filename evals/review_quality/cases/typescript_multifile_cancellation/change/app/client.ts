/** Normalize reader results before exposing them to the synchronization service. */
import { Reader, ReadOptions, Row } from './models';
export async function readRows(reader: Reader, ids: string[], options: ReadOptions): Promise<Row[]> {
  const rows = await reader.read(ids);
  return rows.map(row => ({ ...row }));
}
