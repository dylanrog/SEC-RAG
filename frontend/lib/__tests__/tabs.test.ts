import { expect, test } from "vitest";

import { closeTab, initialTabState, MAX_TABS, openTab } from "../tabs";

function openAll(...accessions: string[]) {
  return accessions.reduce(openTab, initialTabState);
}

test("opening a filing adds it and makes it active", () => {
  const state = openTab(initialTabState, "A");
  expect(state.open).toEqual(["A"]);
  expect(state.active).toBe("A");
});

test("reopening an open filing activates it without duplicating or reordering", () => {
  const state = openTab(openAll("A", "B"), "A");
  expect(state.open).toEqual(["A", "B"]);
  expect(state.active).toBe("A");
});

test("opening beyond the cap evicts the least recently active tab", () => {
  // A opened first, then B, then C, then A re-activated -> B is least recent.
  const state = openTab(openTab(openAll("A", "B", "C"), "A"), "D");
  expect(state.open).toHaveLength(MAX_TABS);
  expect(state.open).toEqual(["A", "C", "D"]);
  expect(state.active).toBe("D");
});

test("an evicted filing can be reopened", () => {
  const evicted = openTab(openTab(openAll("A", "B", "C"), "A"), "D");
  const state = openTab(evicted, "B");
  expect(state.open).toContain("B");
  expect(state.active).toBe("B");
  expect(state.open).toHaveLength(MAX_TABS);
});

test("closing the active tab activates the next most recent", () => {
  const state = closeTab(openAll("A", "B"), "B");
  expect(state.open).toEqual(["A"]);
  expect(state.active).toBe("A");
});

test("closing the last tab leaves nothing active", () => {
  const state = closeTab(openAll("A"), "A");
  expect(state.open).toEqual([]);
  expect(state.active).toBeNull();
});

test("closing an inactive tab leaves the active one alone", () => {
  const state = closeTab(openAll("A", "B"), "A");
  expect(state.active).toBe("B");
});

test("openTab does not mutate the state it was given", () => {
  const before = openAll("A");
  const after = openTab(before, "B");
  expect(before.open).toEqual(["A"]);
  expect(after).not.toBe(before);
});
