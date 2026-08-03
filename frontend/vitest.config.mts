import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // node by default — only highlight.test.ts opts into jsdom, via a
    // `@vitest-environment jsdom` docblock at the top of that file. Running
    // every spec in jsdom would slow the suite down for no benefit.
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
