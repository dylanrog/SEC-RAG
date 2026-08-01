/**
 * @vitest-environment jsdom
 */
import { beforeAll, beforeEach, expect, test, vi } from "vitest";

import { HIGHLIGHT_CLASS, applyHighlight } from "../highlight";

beforeAll(() => {
  // jsdom implements no layout, so scrollIntoView does not exist on Element.
  // Without this stub every test here throws TypeError.
  Element.prototype.scrollIntoView = vi.fn();
});

let container: HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div");
  container.innerHTML = `
    <p><span data-sid="10">First.</span></p>
    <p><span data-sid="11">Second.</span></p>
    <p><span data-sid="12">Third.</span></p>`;
});

test("adds the class to every cited sid", () => {
  applyHighlight(container, [10, 12]);
  expect(container.querySelector('[data-sid="10"]')?.className).toBe(HIGHLIGHT_CLASS);
  expect(container.querySelector('[data-sid="12"]')?.className).toBe(HIGHLIGHT_CLASS);
  expect(container.querySelector('[data-sid="11"]')?.className).toBe("");
});

test("clears the previous highlight before applying the next", () => {
  applyHighlight(container, [10]);
  applyHighlight(container, [11]);
  expect(container.querySelector('[data-sid="10"]')?.className).toBe("");
  expect(container.querySelector('[data-sid="11"]')?.className).toBe(HIGHLIGHT_CLASS);
});

test("scrolls the first cited sentence into view", () => {
  applyHighlight(container, [11, 12]);
  const first = container.querySelector('[data-sid="11"]');
  expect(first?.scrollIntoView).toHaveBeenCalledTimes(1);
});

test("an unknown sid highlights nothing and does not throw", () => {
  expect(() => applyHighlight(container, [999])).not.toThrow();
  expect(container.querySelectorAll(`.${HIGHLIGHT_CLASS}`)).toHaveLength(0);
});

test("an empty sid list clears everything", () => {
  applyHighlight(container, [10]);
  applyHighlight(container, []);
  expect(container.querySelectorAll(`.${HIGHLIGHT_CLASS}`)).toHaveLength(0);
});
