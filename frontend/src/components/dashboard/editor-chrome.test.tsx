import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import {
  EditorChrome,
  EditorChromeProvider,
  useEditorChromeContent,
} from "./editor-chrome";

afterEach(cleanup);
function Header() {
  return (
    <header data-testid="header">
      {useEditorChromeContent() || "Ordinary header"}
    </header>
  );
}
it("moves editor actions into the shared header and restores it on exit", () => {
  const view = render(
    <EditorChromeProvider>
      <Header />
      <EditorChrome>
        <button>Save draft</button>
      </EditorChrome>
    </EditorChromeProvider>,
  );
  expect(screen.getByTestId("header")).toContainElement(
    screen.getByRole("button", { name: "Save draft" }),
  );
  view.rerender(
    <EditorChromeProvider>
      <Header />
    </EditorChromeProvider>,
  );
  expect(screen.getByTestId("header")).toHaveTextContent("Ordinary header");
});
it("keeps expanded editor actions local rather than behind the overlay", () => {
  render(
    <EditorChromeProvider>
      <Header />
      <main>
        <EditorChrome local>
          <button>Publish</button>
        </EditorChrome>
      </main>
    </EditorChromeProvider>,
  );
  expect(screen.getByTestId("header")).toHaveTextContent("Ordinary header");
  expect(screen.getByRole("main")).toContainElement(
    screen.getByRole("button", { name: "Publish" }),
  );
});
