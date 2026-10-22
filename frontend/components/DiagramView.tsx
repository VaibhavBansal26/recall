import type { DiagramItem } from "@/lib/events";
import { MermaidView } from "./MermaidView";
import { StepsView } from "./StepsView";

export function DiagramView({ diagram }: { diagram: DiagramItem }) {
  return diagram.kind === "mermaid" ? (
    <MermaidView source={diagram.source} />
  ) : (
    <StepsView source={diagram.source} />
  );
}
