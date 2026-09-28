import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductLinks } from "./product-links";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("ProductLinks", () => {
  it.each(["0.2.0", "v0.2.0"])("links %s to its exact release", (version) => {
    vi.stubEnv("NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY", "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/");
    render(<ProductLinks version={version} sha="1234567890" />);
    expect(screen.getByRole("link", { name: "v0.2.0" })).toHaveAttribute("href", "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/releases/tag/v0.2.0");
    expect(screen.getByRole("link", { name: "TierX.Tech" })).toHaveAttribute("href", "https://tierx.tech");
    expect(screen.getByText("1234567")).toBeInTheDocument();
    expect(screen.queryByText("Source code (AGPL)")).not.toBeInTheDocument();
  });

  it("uses the release list for a development build", () => {
    render(<ProductLinks version="development" sha="development" />);
    const link = screen.getByRole("link", { name: "development" });
    expect(link.getAttribute("href")).toMatch(/\/releases$/);
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
