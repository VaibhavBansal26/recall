import { create } from "zustand";
import {
  applyUndo,
  initialViewState,
  mergeNotes,
  reduceEvent,
  type DiagramItem,
  type NoteCard,
  type ServerEvent,
  type ViewState,
} from "./events";

export type Connection = "connecting" | "connected" | "closed";

interface SessionStore extends ViewState {
  connection: Connection;
  setConnection: (connection: Connection) => void;
  apply: (event: ServerEvent) => void;
  setNotes: (notes: NoteCard[]) => void;
  syncNotes: (fetched: NoteCard[]) => void;
  setDiagram: (diagram: DiagramItem) => void;
  markSaved: () => void;
  dismissTeachBack: () => void;
  undone: (eventId: string) => void;
}

export const useSessionStore = create<SessionStore>((set) => ({
  ...initialViewState,
  connection: "connecting",
  setConnection: (connection) => set({ connection }),
  apply: (event) => set((state) => reduceEvent(state, event)),
  setNotes: (notes) => set({ notes }),
  syncNotes: (fetched) => set((state) => ({ notes: mergeNotes(state.notes, fetched) })),
  setDiagram: (diagram) =>
    set((state) => ({ diagrams: { ...state.diagrams, [diagram.note_id]: diagram } })),
  markSaved: () =>
    set((state) => ({
      explanation: state.explanation ? { ...state.explanation, saved: true } : null,
    })),
  dismissTeachBack: () => set({ teachBack: null }),
  undone: (eventId) => set((state) => ({ notes: applyUndo(state.notes, eventId) })),
}));
