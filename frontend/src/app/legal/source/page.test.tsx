import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SourceCodePage from "./page";

afterEach(() => vi.unstubAllEnvs());

it("links the configured release repository and exact tag", () => {
  vi.stubEnv("NEXT_PUBLIC_TIERX_RELEASE_VERSION", "0.2.0");
  vi.stubEnv("NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY", "https://github.com/example/tierx/");
  render(<SourceCodePage />);
  expect(screen.getByText("Tagged corresponding source").getAttribute("href"))
    .toBe("https://github.com/example/tierx/tree/v0.2.0");
  expect(screen.getByText("Build and installation guide").getAttribute("href"))
    .toBe("https://github.com/example/tierx/blob/v0.2.0/SOURCE.md");
});

it("rejects a release missing its source repository", () => {
  vi.stubEnv("NEXT_PUBLIC_TIERX_RELEASE_VERSION", "0.2.0");
  vi.stubEnv("NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY", "");
  expect(() => SourceCodePage()).toThrow("requires NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY");
});
