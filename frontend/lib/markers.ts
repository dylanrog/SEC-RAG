export type Segment = string | { marker: number };

/**
 * Split answer prose into literal text and citation markers.
 *
 * Markers are `[1]`-style and digits only, so `[1A]` (an Item reference, which
 * appears constantly in filings) stays literal text. The regex is built inside
 * the function so its `lastIndex` can never leak between calls.
 */
export function splitOnMarkers(text: string): Segment[] {
  const pattern = /\[(\d{1,3})\]/g;
  const segments: Segment[] = [];
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) segments.push(text.slice(cursor, index));
    segments.push({ marker: Number(match[1]) });
    cursor = index + match[0].length;
  }
  if (cursor < text.length) segments.push(text.slice(cursor));
  return segments;
}
