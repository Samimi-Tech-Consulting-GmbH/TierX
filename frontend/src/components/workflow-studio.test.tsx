import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { GraphJsonEditor, WorkflowStudio, WorkflowCanvas } from "./workflow-studio";
import { ReactFlow } from "@xyflow/react";
import * as workflows from "@/lib/workflows";
import type { FlowGraph } from "@/lib/workflows";
const auth = vi.hoisted(()=>({user:null as {role:string}|null}));
vi.mock("@/lib/auth",()=>({useAuth:()=>auth}));
vi.mock("@xyflow/react",async()=>({...await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react"),ReactFlow:vi.fn(()=>null),Background:()=>null,Controls:()=>null,Handle:()=>null}));
const graph:FlowGraph={format_version:"2.0",nodes:[{id:"entry",type:"entry",config:{}},{id:"done",type:"complete",config:{}}],edges:[]};
describe("Graph JSON import",()=>{
  it("does not replace controlled nodes on measurement or selection events",()=>{
    const change=vi.fn();render(<WorkflowCanvas graph={graph} onChange={change}/>);
    const props=vi.mocked(ReactFlow).mock.calls.at(-1)![0];
    props.onNodesChange?.([{id:"entry",type:"dimensions",dimensions:{width:180,height:90}}]);
    props.onNodesChange?.([{id:"entry",type:"select",selected:true}]);
    expect(change).not.toHaveBeenCalled();
    props.onNodesChange?.([{id:"entry",type:"position",position:{x:50,y:40}}]);
    expect(change.mock.calls[0][0].nodes[0].position).toEqual({x:50,y:40});
  });
  it("opens the dedicated playbook library instead of an empty workflow screen",async()=>{
    auth.user={role:"PLATFORM_ADMIN"};
    const request=vi.spyOn(workflows,"workflowRequest").mockResolvedValue({items:[],node_types:[],templates:[]});
    render(<WorkflowStudio initialKind="playbook"/>);
    expect(await screen.findByRole("button",{name:"New playbook"})).toBeInTheDocument();
    expect(screen.getByRole("button",{name:"playbooks"})).toHaveAttribute("aria-pressed","true");
    request.mockRestore();auth.user=null;
  });
  it("never imports on blur and rejects an outdated edit buffer",()=>{
    const apply=vi.fn();
    const view=render(<GraphJsonEditor graph={graph} readOnly={false} onApply={apply}/>);
    const editor=screen.getByLabelText("Graph JSON");
    fireEvent.change(editor,{target:{value:JSON.stringify({...graph,edges:[{id:"x",source:"entry",target:"done"}]})}});
    fireEvent.blur(editor);expect(apply).not.toHaveBeenCalled();
    view.rerender(<GraphJsonEditor graph={{...graph,nodes:[...graph.nodes,{id:"new",type:"validation",config:{}}]}} readOnly={false} onApply={apply}/>);
    expect(screen.getByRole("button",{name:"Apply JSON import"})).toBeDisabled();
    fireEvent.click(screen.getByRole("button",{name:"Reload current graph"}));
    expect((screen.getByLabelText("Graph JSON") as HTMLTextAreaElement).value).toContain('"new"');
  });
});
