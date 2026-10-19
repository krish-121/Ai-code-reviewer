/** Transport values and cancellation options used by every synchronization layer. */
export interface Row { id: string; value: string }
export interface ReadOptions { signal?: AbortSignal }
export interface Reader { read(ids: string[], options?: ReadOptions): Promise<Row[]> }
export interface SyncResult { count: number; ids: string[] }
