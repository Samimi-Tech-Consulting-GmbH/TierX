"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
  type Dispatch,
  type SetStateAction,
} from "react";

// Separate read/write contexts keep header updates from rerendering the editor.
const Content = createContext<ReactNode>(null);
const SetContent = createContext<Dispatch<SetStateAction<ReactNode>> | null>(
  null,
);

export function EditorChromeProvider({ children }: { children: ReactNode }) {
  const [content, setContent] = useState<ReactNode>(null);
  return (
    <SetContent.Provider value={setContent}>
      <Content.Provider value={content}>{children}</Content.Provider>
    </SetContent.Provider>
  );
}
export const useEditorChromeContent = () => useContext(Content);

export function EditorChrome({
  children,
  local = false,
}: {
  children: ReactNode;
  local?: boolean;
}) {
  const setContent = useContext(SetContent);
  useEffect(() => {
    if (!setContent || local) return;
    setContent(children);
    return () => setContent(null);
  }, [setContent, children, local]);
  return !setContent || local ? <>{children}</> : null;
}
