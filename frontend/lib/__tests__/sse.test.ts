import { expect, test } from "vitest";

import { parseSSE } from "../sse";

test("parses one complete frame", () => {
  const { events, rest } = parseSSE('event: token\ndata: {"text":"hi"}\n\n');
  expect(events).toEqual([{ event: "token", data: { text: "hi" } }]);
  expect(rest).toBe("");
});

test("parses two frames from one buffer", () => {
  const buffer =
    'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"text":"b"}\n\n';
  const { events } = parseSSE(buffer);
  expect(events.map((e) => (e.data as { text: string }).text)).toEqual(["a", "b"]);
});

test("returns an incomplete trailing frame as rest", () => {
  const { events, rest } = parseSSE('event: token\ndata: {"text":"a"}\n\nevent: tok');
  expect(events).toHaveLength(1);
  expect(rest).toBe("event: tok");
});

test("a frame split across two chunks parses once rejoined", () => {
  const first = parseSSE('event: citation\ndata: {"marker":1,');
  expect(first.events).toEqual([]);
  const second = parseSSE(first.rest + '"verified":true}\n\n');
  expect(second.events).toEqual([
    { event: "citation", data: { marker: 1, verified: true } },
  ]);
});

test("joins multi-line data before parsing", () => {
  const { events } = parseSSE('event: token\ndata: {"text":\ndata: "hi"}\n\n');
  expect(events[0].data).toEqual({ text: "hi" });
});

test("preserves an unknown event name", () => {
  const { events } = parseSSE("event: heartbeat\ndata: {}\n\n");
  expect(events[0].event).toBe("heartbeat");
});

test("drops a frame whose data is not JSON without losing later frames", () => {
  const { events } = parseSSE(
    "event: token\ndata: not json\n\nevent: done\ndata: {}\n\n",
  );
  expect(events).toEqual([{ event: "done", data: {} }]);
});

test("tolerates CRLF line endings", () => {
  const { events } = parseSSE('event: token\r\ndata: {"text":"hi"}\r\n\r\n');
  expect(events[0].data).toEqual({ text: "hi" });
});

test("an empty buffer yields nothing", () => {
  expect(parseSSE("")).toEqual({ events: [], rest: "" });
});
