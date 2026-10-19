/** Preserve request order while rejecting empty or repeated external IDs. */
export function ids(values: string[]): string[] {
  if (values.some(value => !value.trim())) throw new Error('empty id');
  if (new Set(values).size !== values.length) throw new Error('duplicate id');
  return [...values];
}
