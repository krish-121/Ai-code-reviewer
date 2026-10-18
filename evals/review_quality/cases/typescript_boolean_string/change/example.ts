/** Decode the literal configuration strings "true" and "false". */
export function enabled(value: "true" | "false"): boolean {
  return Boolean(value);
}
