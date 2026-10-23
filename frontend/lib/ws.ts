import type { ClientEvent, ServerEvent } from "./events";
import type { Connection } from "./store";

import { AUTH_EVENT, getAuthStatus, wsUrl } from "./http";

interface Handlers {
  onEvent: (event: ServerEvent) => void;
  onStatus: (status: Connection) => void;
}

export class VoiceSocket {
  private socket: WebSocket | null = null;

  constructor(private handlers: Handlers) {}

  connect(track: string): void {
    this.socket?.close(); // switching tracks replaces the connection
    const socket = new WebSocket(wsUrl());
    let opened = false;
    this.socket = socket;
    this.handlers.onStatus("connecting");
    // Callbacks from a replaced or closed socket (e.g. React strict-mode remount) are ignored.
    const live = () => this.socket === socket;
    socket.onopen = () => {
      if (!live()) return;
      opened = true;
      this.handlers.onStatus("connected");
      this.send({ type: "start", track });
    };
    socket.onmessage = (msg) => {
      if (live() && typeof msg.data === "string") {
        this.handlers.onEvent(JSON.parse(msg.data) as ServerEvent);
      }
    };
    socket.onclose = () => {
      if (!live()) return;
      this.handlers.onStatus("closed");
      // A handshake the server refused is most likely an expired login.
      if (!opened) {
        getAuthStatus()
          .then((s) => s.auth_required && !s.authenticated && window.dispatchEvent(new Event(AUTH_EVENT)))
          .catch(() => undefined);
      }
    };
  }

  send(event: ClientEvent): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(event));
  }

  /** Raw 16 kHz mono PCM microphone frames. */
  sendAudio(pcm: ArrayBuffer): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(pcm);
  }

  close(): void {
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }
}
