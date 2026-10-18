/** Check whether a parsed JSON value has a string name. */
function hasName(value: unknown): value is { name: string } {
  return typeof value === "object" && value !== null && "name" in value && typeof value.name === "string";
}
/** Read a string name from a parsed JSON value, otherwise return null. */
export function readName(value: unknown): string | null {
  return hasName(value) ? value.name : null;
}
