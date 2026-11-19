import { useState } from "react";
import { ReactFlow, ReactFlowProvider, useReactFlow, type Node, type Edge } from "@xyflow/react";
import { Minus, Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { display, type RecordData } from "@/lib/aegis-api";
export function TraceGraph({
  nodes: sourceNodes,
  edges: sourceEdges,
}: {
  nodes: RecordData[];
  edges: RecordData[];
}) {
  return (
    <ReactFlowProvider>
      <GraphCanvas sourceNodes={sourceNodes} sourceEdges={sourceEdges} />
    </ReactFlowProvider>
  );
}
function GraphCanvas({
  sourceNodes,
  sourceEdges,
}: {
  sourceNodes: RecordData[];
  sourceEdges: RecordData[];
}) {
  const [selected, setSelected] = useState<RecordData | null>(null);
  const flow = useReactFlow();
  const types = [...new Set(sourceNodes.map((n) => display(n["type"])))];
  const nodes: Node[] = sourceNodes.map((n, i) => ({
    id: display(n["id"]),
    position: {
      x: types.indexOf(display(n["type"])) * 230,
      y: sourceNodes.slice(0, i).filter((other) => other["type"] === n["type"]).length * 120,
    },
    data: {
      label: display(
        n["label"] ?? n["text"] ?? n["source"] ?? n["decision"] ?? n["code"] ?? n["id"],
      ).slice(0, 60),
      original: n,
    },
    className: `trace-node node-${display(n["type"]).toLowerCase()}`,
  }));
  const valid = new Set(nodes.map((n) => n["id"]));
  const edges: Edge[] = sourceEdges
    .map((e, i) => ({
      id: display(e["id"] ?? `edge-${i}`),
      source: display(e["source"] ?? e["from"]),
      target: display(e["target"] ?? e["to"]),
      label: display(e["type"]),
      className:
        display(e["type"]).includes("CONTRADICT") || display(e["type"]).includes("CONFLICT")
          ? "edge-contradiction"
          : "edge-supported",
    }))
    .filter((e) => valid.has(e["source"]) && valid.has(e["target"]));
  return (
    <div className="graph-workspace">
      <div className="graph-canvas graph-loaded">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          minZoom={0.2}
          maxZoom={2}
          onNodeClick={(_, node) => setSelected(node.data["original"] as RecordData)}
          onEdgeClick={(_, edge) =>
            setSelected(
              sourceEdges.find((e, i) => display(e["id"] ?? `edge-${i}`) === edge.id) ?? null,
            )
          }
          proOptions={{ hideAttribution: true }}
        />
        <div className="graph-controls">
          <Button variant="outline" size="icon" title="Zoom in" onClick={() => flow.zoomIn()}>
            <Plus />
          </Button>
          <Button variant="outline" size="icon" title="Zoom out" onClick={() => flow.zoomOut()}>
            <Minus />
          </Button>
          <Button variant="outline" size="icon" title="Reset view" onClick={() => flow.fitView()}>
            <RefreshCw />
          </Button>
        </div>
      </div>
      <aside className="graph-inspector">
        <h3>{selected ? "Selected entity" : "Node inspector"}</h3>
        {selected ? (
          Object.entries(selected).map(([key, value]) => (
            <p key={key}>
              <span className="font-mono text-primary">{key}</span>
              <br />
              {display(value)}
            </p>
          ))
        ) : (
          <p>Select a node or relationship.</p>
        )}
      </aside>
    </div>
  );
}
