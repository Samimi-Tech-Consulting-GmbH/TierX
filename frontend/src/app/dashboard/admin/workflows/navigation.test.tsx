import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OldAdminEntry from "../ingestion-v2/page";
import OldTenantEntry from "../../[tenantId]/ingestion-v2/page";
import PlaybookAlias from "../playbook-flows/page";
import Playbooks from "../playbooks/page";
vi.mock("next/navigation",()=>({redirect:(path:string)=>{throw new Error(path);}}));
vi.mock("@/components/workflow-studio",()=>({WorkflowStudio:({initialKind}:{initialKind:string})=><p>Unified {initialKind} library</p>}));
describe("Unified workflow navigation",()=>{
  it.each([OldAdminEntry,OldTenantEntry])("redirects old ingestion entry screens to one Studio",Page=>{
    expect(()=>Page()).toThrow("/dashboard/admin/workflows");
  });
  it("uses the canonical playbook library and redirects its old alias",()=>{
    render(<Playbooks/>);expect(screen.getByText("Unified playbook library")).toBeInTheDocument();
    expect(()=>PlaybookAlias()).toThrow("/dashboard/admin/playbooks");
  });
});
