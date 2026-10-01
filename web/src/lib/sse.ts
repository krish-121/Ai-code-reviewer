// A minimal Server-Sent Events parser. The browser's EventSource cannot send an
// Authorization header, so progress is read with fetch() and parsed here instead.

export interface ServerSentEvent {
  event: string;
  data: string;
}

/**
 * Split a buffer into complete events (separated by a blank line) and the incomplete rest,
 * which the caller keeps until more bytes arrive.
 */
export function parseServerSentEvents(buffer: string): {
  events: ServerSentEvent[];
  rest: string;
} {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events = blocks.map(parseBlock).filter((e): e is ServerSentEvent => e !== null);
  return { events, rest };
}

function parseBlock(block: string): ServerSentEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}
