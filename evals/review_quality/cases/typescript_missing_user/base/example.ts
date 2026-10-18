export interface User { id: number; name: string; }
/** Return the matching name, or "Unknown" when the id is absent. */
export function userName(users: User[], id: number): string {
  return users.find((user) => user.id === id)?.name ?? "Unknown";
}
