/** Read a string name from a parsed JSON value, otherwise return null. */
export function readName(value: unknown): string | null {
  if (typeof value === "object" && value !== null && "name" in value && typeof value.name === "string") {
    return value.name;
  }
  return null;
}
