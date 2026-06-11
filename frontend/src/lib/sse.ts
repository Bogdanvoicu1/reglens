// Minimal SSE parser over a byte stream. EventSource cannot POST, so we read
// the fetch body manually. Frames are separated by a blank line; each frame
// carries `event:` and `data:` lines. The buffer survives chunk boundaries
// that split frames mid-line.

export interface RawSSE {
  event: string;
  data: string;
}

export function createSSEBuffer() {
  let buffer = "";
  return {
    push(chunk: string): RawSSE[] {
      buffer += chunk;
      const frames: RawSSE[] = [];
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let event = "message";
        const dataLines: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7).trim();
          else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
        }
        if (dataLines.length > 0) frames.push({ event, data: dataLines.join("\n") });
      }
      return frames;
    },
  };
}

export async function streamSSE(
  response: Response,
  onEvent: (e: RawSSE) => void,
): Promise<void> {
  if (!response.body) throw new Error("Response has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const sse = createSSEBuffer();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const frame of sse.push(decoder.decode(value, { stream: true }))) {
      onEvent(frame);
    }
  }
}
