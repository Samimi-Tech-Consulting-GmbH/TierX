import Link from "next/link";
import { studioButton } from "./workflow-library";

export function ToolNavigation({
  active,
}: {
  active: "connectors" | "python";
}) {
  return (
    <nav aria-label="Tools and integrations" className="flex gap-2">
      <Link
        className={studioButton}
        aria-current={active === "connectors" ? "page" : undefined}
        href="/dashboard/admin/settings/connectors"
      >
        REST & MCP integrations
      </Link>
      <Link
        className={studioButton}
        aria-current={active === "python" ? "page" : undefined}
        href="/dashboard/admin/settings/python-tools"
      >
        Python tools
      </Link>
    </nav>
  );
}
