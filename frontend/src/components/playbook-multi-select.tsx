"use client";

import { useId, useRef, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import { Popover } from "@base-ui/react/popover";

type Playbook = { code: string; name: string };

export function PlaybookMultiSelect({
  items,
  value,
  onChange,
}: {
  items: Playbook[];
  value: string[];
  onChange: (codes: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const search = useRef<HTMLInputElement>(null);
  const id = useId();
  const unique = [
    ...new Map(items.map((item) => [item.code, item])).values(),
  ].sort((a, b) => a.name.localeCompare(b.name));
  const choices = [
    ...unique,
    ...value
      .filter((code) => !unique.some((item) => item.code === code))
      .map((code) => ({ code, name: `Unavailable playbook · ${code}` })),
  ];
  const filtered = choices.filter((item) =>
    `${item.name} ${item.code}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  return (
    <div className="space-y-2">
      <span id={`${id}-label`} className="text-xs">
        LLM candidate playbooks
      </span>
      <Popover.Root>
        <Popover.Trigger
          aria-labelledby={`${id}-label ${id}-count`}
          className="flex w-full items-center justify-between gap-2 rounded-lg border border-input bg-background px-3 py-2 text-sm"
        >
          <span id={`${id}-count`}>
            {value.length ? `${value.length} selected` : "Choose playbooks"}
          </span>
          <ChevronDown size={15} />
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Positioner align="start" sideOffset={4} className="z-[100]">
            <Popover.Popup
              initialFocus={search}
              aria-labelledby={`${id}-label`}
              className="w-[var(--anchor-width)] max-w-[calc(100vw-2rem)] rounded-lg border bg-popover p-2 text-popover-foreground shadow-lg"
            >
              <label className="relative block">
                <Search
                  size={14}
                  className="absolute left-2 top-2.5 text-muted-foreground"
                />
                <input
                  ref={search}
                  aria-label="Search candidate playbooks"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search by name or code…"
                  className="w-full rounded border bg-background py-2 pl-7 pr-2 text-xs"
                />
              </label>
              <div className="mt-2 max-h-64 overflow-y-auto overscroll-contain">
                {filtered.map((item) => (
                  <label
                    key={item.code}
                    className="flex cursor-pointer items-start gap-2 rounded px-2 py-2 text-xs hover:bg-muted"
                  >
                    <input
                      type="checkbox"
                      checked={value.includes(item.code)}
                      disabled={
                        !value.includes(item.code) && value.length >= 20
                      }
                      onChange={(event) =>
                        onChange(
                          event.target.checked
                            ? [...value, item.code]
                            : value.filter((code) => code !== item.code),
                        )
                      }
                    />
                    <span className="min-w-0">
                      <span className="block break-words">{item.name}</span>
                      <span className="text-muted-foreground">{item.code}</span>
                    </span>
                  </label>
                ))}
                {!filtered.length && (
                  <p className="p-2 text-xs text-muted-foreground">
                    No matching playbooks.
                  </p>
                )}
              </div>
              <p className="border-t px-2 pt-2 text-xs text-muted-foreground">
                {value.length} / 20 candidates selected
              </p>
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      </Popover.Root>
      {!!value.length && (
        <div className="flex flex-wrap gap-1">
          {value.map((code) => (
            <button
              type="button"
              key={code}
              aria-label={`Remove ${choices.find((item) => item.code === code)?.name || code}`}
              className="inline-flex max-w-full items-center gap-1 rounded border bg-muted px-2 py-1 text-xs"
              onClick={() => onChange(value.filter((item) => item !== code))}
            >
              <span className="truncate">
                {choices.find((item) => item.code === code)?.name || code}
              </span>
              <X size={12} className="shrink-0" />
            </button>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Search your playbook library and choose up to 20 candidates for this LLM
        call. No canvas connections are required.
      </p>
    </div>
  );
}
