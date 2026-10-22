"use client";

import "@xyflow/react/dist/style.css";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useMemo } from "react";
import type { GraphOut } from "@/lib/api";
import { forceLayout, strengthColor } from "@/lib/layout";

type NoteNodeData = {
  title: string;
  strength: number | null;
  fragile: boolean;
  unconfirmed: boolean;
};
type NoteFlowNode = Node<NoteNodeData, "note">;

function NoteNode({ data, selected }: NodeProps<NoteFlowNode>) {
  return (
    <div
      data-testid="map-node"
      data-fragile={data.fragile}
      title={data.title}
      style={{ background: strengthColor(data.strength) }}
      className={`max-w-[11rem] rounded-xl border-2 px-3 py-2 text-xs text-neutral-900 shadow-sm ${
        selected ? "ring-2 ring-indigo-500" : ""
      } ${data.fragile ? "border-red-600" : "border-neutral-400"} ${
        data.unconfirmed ? "border-dashed" : ""
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-neutral-400" />
      {data.fragile && (
        <span role="img" aria-label="Fragile" className="mr-1">
          ⚠
        </span>
      )}
      {data.title}
      <Handle type="source" position={Position.Bottom} className="!bg-neutral-400" />
    </div>
  );
}

const nodeTypes = { note: NoteNode };

interface Props {
  graph: GraphOut;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

export function MemoryMap({ graph, selectedId, onSelect }: Props) {
  const nodes = useMemo<NoteFlowNode[]>(() => {
    const ids = graph.nodes.map((n) => n.id);
    const pos = forceLayout(
      ids,
      graph.edges.map((e) => ({ source: e.from_note_id, target: e.to_note_id })),
    );
    return graph.nodes.map((n) => ({
      id: n.id,
      type: "note",
      position: pos[n.id],
      selected: n.id === selectedId,
      data: {
        title: n.title,
        strength: n.strength ?? null,
        fragile: n.fragile,
        unconfirmed: n.origin === "assistant" && !n.confirmed,
      },
    }));
  }, [graph, selectedId]);

  const edges = useMemo<Edge[]>(
    () =>
      graph.edges.map((e) => ({
        id: e.id,
        source: e.from_note_id,
        target: e.to_note_id,
        label: e.confirmed ? e.kind.replace("_", " ") : `${e.kind.replace("_", " ")} (unconfirmed)`,
        animated: !e.confirmed,
        markerEnd: { type: MarkerType.ArrowClosed },
        // Assistant-proposed links are dashed amber until the user confirms them.
        style: e.confirmed
          ? { strokeWidth: 1.5 }
          : { strokeWidth: 1.5, strokeDasharray: "6 4", stroke: "#d97706" },
        labelStyle: { fontSize: 10, fill: e.confirmed ? undefined : "#d97706" },
        data: { confirmed: e.confirmed },
      })),
    [graph.edges],
  );

  return (
    <div className="h-full w-full" data-testid="memory-map">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        colorMode="system"
        fitView
        nodesConnectable={false}
        onNodeClick={(_, node) => onSelect(node.id)}
        onPaneClick={() => onSelect(null)}
        aria-label="Memory map"
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
