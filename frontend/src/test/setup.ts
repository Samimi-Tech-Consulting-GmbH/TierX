import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals are disabled, so Testing Library cannot register this itself.
// Unmount React roots before jsdom is destroyed and pending effects run.
afterEach(cleanup);
