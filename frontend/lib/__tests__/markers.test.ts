import { expect, test } from "vitest";

import { splitOnMarkers } from "../markers";

test("text with no marker is one segment", () => {
  expect(splitOnMarkers("Just prose.")).toEqual(["Just prose."]);
});

test("splits around a single marker", () => {
  expect(splitOnMarkers("Sales rose [1].")).toEqual([
    "Sales rose ",
    { marker: 1 },
    ".",
  ]);
});

test("handles a multi-digit marker", () => {
  expect(splitOnMarkers("see [10]")).toEqual(["see ", { marker: 10 }]);
});

test("handles adjacent markers", () => {
  expect(splitOnMarkers("both [1][2] agree")).toEqual([
    "both ",
    { marker: 1 },
    { marker: 2 },
    " agree",
  ]);
});

test("leaves non-numeric brackets alone", () => {
  expect(splitOnMarkers("see Item [1A] here")).toEqual(["see Item [1A] here"]);
});

test("handles a marker at the very start", () => {
  expect(splitOnMarkers("[3] leads")).toEqual([{ marker: 3 }, " leads"]);
});

test("an empty string yields no segments", () => {
  expect(splitOnMarkers("")).toEqual([]);
});
