import { describe, expect, it } from "vitest";
import { createSSEBuffer } from "./sse";

describe("createSSEBuffer", () => {
  it("parses a complete frame", () => {
    const sse = createSSEBuffer();
    const frames = sse.push('event: token\ndata: {"token":"hi"}\n\n');
    expect(frames).toEqual([{ event: "token", data: '{"token":"hi"}' }]);
  });

  it("handles frames split across chunks mid-line", () => {
    const sse = createSSEBuffer();
    expect(sse.push("event: tok")).toEqual([]);
    expect(sse.push('en\ndata: {"a":1}')).toEqual([]);
    expect(sse.push("\n\nevent: done\n")).toEqual([
      { event: "token", data: '{"a":1}' },
    ]);
    expect(sse.push('data: {"b":2}\n\n')).toEqual([{ event: "done", data: '{"b":2}' }]);
  });

  it("parses multiple frames in one chunk", () => {
    const sse = createSSEBuffer();
    const frames = sse.push("event: a\ndata: 1\n\nevent: b\ndata: 2\n\n");
    expect(frames.map((f) => f.event)).toEqual(["a", "b"]);
  });

  it("ignores keep-alive frames without data", () => {
    const sse = createSSEBuffer();
    expect(sse.push(":\n\n")).toEqual([]);
  });
});
