import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProductLinks } from "./product-links";
import { useLatestRelease } from "@/lib/use-latest-release";
vi.mock("@/lib/use-latest-release", () => ({ useLatestRelease: vi.fn() }));
beforeEach(() =>
  vi.mocked(useLatestRelease).mockReturnValue({ release: null, loading: true }),
);

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("ProductLinks", () => {
  it.each(["0.2.0", "v0.2.0"])("links %s to its exact release", (version) => {
    vi.stubEnv(
      "NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY",
      "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/",
    );
    render(<ProductLinks version={version} sha="1234567890" />);
    expect(screen.getByRole("link", { name: "v0.2.0" })).toHaveAttribute(
      "href",
      "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/releases/tag/v0.2.0",
    );
    expect(screen.getByRole("link", { name: "TierX.Tech" })).toHaveAttribute(
      "href",
      "https://tierx.tech",
    );
    expect(screen.getByRole("link", { name: "v0.2.0" })).toHaveAttribute(
      "title",
      expect.stringContaining("1234567890"),
    );
    expect(screen.queryByText("1234567")).not.toBeInTheDocument();
    expect(screen.queryByText("Source code (AGPL)")).not.toBeInTheDocument();
  });

  it("uses the release list for a development build", () => {
    render(<ProductLinks version="development" sha="development" />);
    const link = screen.getByRole("link", { name: "development" });
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/releases",
    );
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
  it.each(["01.2.0", "0.02.0", "0.2.00", "invalid"])(
    "uses the release list for invalid semantic version %s",
    (version) => {
      render(<ProductLinks version={version} sha="development" />);
      expect(screen.getByRole("link", { name: `v${version}` })).toHaveAttribute(
        "href",
        "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/releases",
      );
    },
  );

  it.each(["", "   "])(
    "falls back for empty repository setting %s",
    (repository) => {
      vi.stubEnv("NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY", repository);
      const { rerender } = render(
        <ProductLinks version="0.2.0" sha="1234567" />,
      );
      expect(screen.getByRole("link", { name: "v0.2.0" })).toHaveAttribute(
        "href",
        "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/releases/tag/v0.2.0",
      );
      rerender(<ProductLinks version="development" sha="development" />);
      expect(screen.getByRole("link", { name: "development" })).toHaveAttribute(
        "href",
        "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/releases",
      );
    },
  );
  it("uses configured corresponding-source repository for installed release links", () => {
    vi.stubEnv(
      "NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY",
      "https://github.com/example/tierx/",
    );
    render(<ProductLinks version="0.2.0" sha="123456789" />);
    expect(screen.getByRole("link", { name: "v0.2.0" })).toHaveAttribute(
      "href",
      "https://github.com/example/tierx/releases/tag/v0.2.0",
    );
  });
  it.each([
    ["0.2.0", "(Update available)"],
    ["0.2.3", "(Latest version)"],
  ])(
    "retains release status alongside product links for %s",
    (version, label) => {
      vi.mocked(useLatestRelease).mockReturnValue({
        loading: false,
        release: {
          enabled: true,
          status: "AVAILABLE",
          latest_version: "0.2.3",
          release_url:
            "https://github.com/Samimi-Tech-Consulting-GmbH/TierX/releases/tag/v0.2.3",
          checked_at: null,
        },
      });
      render(<ProductLinks version={version} sha="123456789" />);
      expect(screen.getByText(label)).toBeVisible();
      expect(screen.getByRole("link", { name: `v${version}` })).toBeVisible();
      expect(screen.getByRole("link", { name: "TierX.Tech" })).toBeVisible();
      expect(
        screen.getByText(label).parentElement?.parentElement,
      ).toContainElement(screen.getByRole("link", { name: `v${version}` }));
      expect(screen.queryByText("1234567")).not.toBeInTheDocument();
    },
  );
  it("provides one icon row with accessible logout, website and repository controls", () => {
    const logout = vi.fn();
    render(<ProductLinks version="0.2.9" sha="abcdef1234" onLogout={logout} />);
    const row = screen.getByRole("navigation", {
      name: "Product and session links",
    });
    const button = within(row).getByRole("button", { name: "Logout" });
    expect(button).toHaveAttribute("title", "Logout");
    fireEvent.click(button);
    expect(logout).toHaveBeenCalledOnce();
    expect(within(row).getAllByRole("link")).toHaveLength(2);
    expect(
      within(row).getByRole("link", {
        name: "GitHub repository (AGPL source code)",
      }),
    ).toHaveAttribute(
      "href",
      "https://github.com/Samimi-Tech-Consulting-GmbH/TierX",
    );
    expect(
      within(row).getByRole("link", { name: "TierX.Tech" }),
    ).toHaveAttribute("rel", "noopener noreferrer");
    expect(row.textContent).toBe("");
  });
});
