/** Synchronization forwards cancellation and never saves a failed or aborted read. */
import { Reader, SyncResult } from './models';
import { Snapshot } from './repository';
import { readRows } from './client';
import { ids as validateIds } from './validation';
export async function synchronize(reader: Reader, snapshot: Snapshot, values: string[], signal?: AbortSignal): Promise<SyncResult> {
  const selected = validateIds(values);
  const rows = await readRows(reader, selected, { signal });
  const received = [...rows];
  snapshot.putAll(received);
  return { count: received.length, ids: received.map(row => row.id) };
}
