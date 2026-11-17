import { useState } from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { PlaybookMultiSelect } from "./playbook-multi-select";

const items = Array.from({ length: 100 }, (_, i) => ({
  code: `pb-${i}`,
  name: `Investigation ${i}`,
}));
afterEach(cleanup);
function Example({ initial = [] }: { initial?: string[] }) {
  const [value, setValue] = useState(initial);
  return (
    <PlaybookMultiSelect items={items} value={value} onChange={setValue} />
  );
}
describe("Playbook candidate multi-select", () => {
  it("searches a large library, retains selections across searches and closes with Escape", async () => {
    const parentKey = vi.fn();
    render(<div onKeyDown={parentKey}><Example /></div>);
    const trigger = screen.getByRole("button", {
      name: /LLM candidate playbooks/,
    });
    fireEvent.click(trigger);
    const search = await screen.findByRole("textbox", {
      name: "Search candidate playbooks",
    });
    fireEvent.change(search, { target: { value: "pb-99" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Investigation 99/ }));
    fireEvent.change(search, { target: { value: "pb-42" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Investigation 42/ }));
    expect(trigger).toHaveTextContent("2 selected");
    expect(
      screen.getByRole("button", { name: "Remove Investigation 99" }),
    ).toBeInTheDocument();
    fireEvent.keyDown(search, { key: "Escape" });
    await waitFor(() =>
      expect(trigger).toHaveAttribute("aria-expanded", "false"),
    );
    expect(parentKey).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Remove Investigation 99" }),
    );
    expect(trigger).toHaveTextContent("1 selected");
  });
  it("keeps the model candidate budget and permits removing unavailable selections", async () => {
    render(
      <Example
        initial={[...items.slice(0, 19).map((item) => item.code), "missing"]}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /LLM candidate playbooks/ }),
    );
    expect(
      await screen.findByRole("checkbox", { name: /Investigation 99/ }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Unavailable playbook/ }),
    );
    expect(
      screen.getByRole("checkbox", { name: /Investigation 99/ }),
    ).not.toBeDisabled();
  });
});
