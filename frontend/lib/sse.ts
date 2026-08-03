import type { SSEEvent } from "./types";

/**
 * Decode as many whole SSE frames as `buffer` contains.
 *
 * Returns the unconsumed remainder as `rest`. The caller must prepend it to
 * the next network chunk: a chunk boundary can fall anywhere, including
 * mid-JSON, and a parser that assumed whole frames would work on localhost
 * and corrupt answers on a slow connection.
 */
export function parseSSE(buffer: string): { events: SSEEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const segments = normalized.split("\n\n");
  // The last segment is whatever follows the final blank line -- either "" or
  // a partial frame. Either way it is not ours to decode yet.
  const rest = segments.pop() ?? "";
  const events: SSEEvent[] = [];

  for (const segment of segments) {
    if (!segment.trim()) continue;
    let name = "message";
    const dataLines: string[] = [];
    for (const line of segment.split("\n")) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) continue;
    try {
      events.push({ event: name, data: JSON.parse(dataLines.join("\n")) });
    } catch {
      // Our server always sends JSON, so this is a corrupt frame. Skipping it
      // beats throwing away every later frame in the same chunk.
    }
  }
  return { events, rest };
}
