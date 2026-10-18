export type Fetcher = (id: string) => Promise<{ active: boolean }>;
/** Return the fetched state, waiting for the injected asynchronous fetcher. */
export async function isActive(id: string, fetcher: Fetcher): Promise<boolean> {
  const result = await fetcher(id);
  return result.active;
}
