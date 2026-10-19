/** A request's signal represents caller cancellation, not a separate new controller. */
import { Reader } from './models';
import { Snapshot } from './repository';
import { synchronize } from './service';
export function refresh(reader: Reader, snapshot: Snapshot, values: string[], signal?: AbortSignal) {
  return synchronize(reader, snapshot, values, signal);
}
