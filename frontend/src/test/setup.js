import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// jsdom has no object-URL support; the lab uses it for the instant local preview.
let counter = 0;
URL.createObjectURL = () => `blob:test/${++counter}`;
URL.revokeObjectURL = () => {};
