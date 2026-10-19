/** Adapt the external reader while forwarding its cancellation contract unchanged. */
import { Reader, ReadOptions, Row } from './models';
export async function readRows(reader: Reader, ids: string[], options: ReadOptions): Promise<Row[]> {
  return reader.read(ids, options);
}
