/** Validate pagination separately from the authenticated organization scope. */
export function pageSize(value: number): number {
  if (!Number.isInteger(value) || value < 1 || value > 100) throw new Error('invalid limit');
  return value;
}
export function organization(value: string): string {
  if (!value.trim()) throw new Error('missing organization');
  return value;
}
