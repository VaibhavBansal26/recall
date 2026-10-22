import type { DiagramItem } from "@/lib/events";
import { parseWalkthrough } from "@/lib/walkthrough";
import { MermaidView } from "./MermaidView";
import { StepsView } from "./StepsView";
import { WalkthroughView } from "./WalkthroughView";

export function DiagramView({ diagram }: { diagram: DiagramItem }) {
  if (diagram.kind === "mermaid") return <MermaidView source={diagram.source} />;
  if (diagram.kind === "walkthrough") {
    const walkthrough = parseWalkthrough(diagram.source);
    if (walkthrough) return <WalkthroughView key={diagram.note_id} walkthrough={walkthrough} />;
    return <p className="text-sm opacity-60">This walkthrough could not be drawn.</p>;
  }
  return <StepsView source={diagram.source} />;
}
