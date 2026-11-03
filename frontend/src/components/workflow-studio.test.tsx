import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { GraphJsonEditor } from "./workflow-studio";
import type { FlowGraph } from "@/lib/workflows";
vi.mock("@/lib/auth",()=>({useAuth:()=>({user:null})}));
vi.mock("@xyflow/react",()=>({ReactFlow:()=>null,Background:()=>null,Controls:()=>null,Handle:()=>null,Position:{Left:"left",Right:"right"}}));
const graph:FlowGraph={format_version:"2.0",nodes:[{id:"entry",type:"entry",config:{}},{id:"done",type:"complete",config:{}}],edges:[]};
describe("Graph JSON import",()=>{
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
