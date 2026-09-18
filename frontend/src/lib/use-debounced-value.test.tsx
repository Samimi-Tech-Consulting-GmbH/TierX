import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "./use-debounced-value";

function Probe({ value }: { value: string }) {
  return <span data-testid="settled">{useDebouncedValue(value)}</span>;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useDebouncedValue", () => {
  it("holds the value back until typing stops", () => {
    vi.useFakeTimers();
    const { rerender } = render(<Probe value="" />);

    rerender(<Probe value="b" />);
    rerender(<Probe value="br" />);
    act(() => void vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1));
    // Still mid-burst: nothing has settled, so no request would have gone out.
    expect(screen.getByTestId("settled")).toHaveTextContent("");

    rerender(<Probe value="brute" />);
    act(() => void vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS));
    expect(screen.getByTestId("settled")).toHaveTextContent("brute");
  });

  it("settles on a cleared box, so clearing the search restores the list", () => {
    vi.useFakeTimers();
    const { rerender } = render(<Probe value="brute" />);
    act(() => void vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS));
    expect(screen.getByTestId("settled")).toHaveTextContent("brute");

    rerender(<Probe value="" />);
    act(() => void vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS));
    expect(screen.getByTestId("settled")).toHaveTextContent("");
  });
});
