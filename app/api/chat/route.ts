import { NextRequest } from "next/server";

export const runtime = "nodejs";

type UpstreamChunk = {
  choices?: Array<{
    delta?: {
      content?: string;
      audio?: { data?: string };
    };
  }>;
};

export async function POST(req: NextRequest) {
  const { message, imageDataUrl } = await req.json();
  if (!message || typeof message !== "string") {
    return new Response(JSON.stringify({ error: "Missing message" }), { status: 400 });
  }

  const apiKey = process.env.DASHSCOPE_API_KEY;
  const baseUrl = process.env.DASHSCOPE_BASE_URL || "https://dashscope.aliyuncs.com/compatible-mode/v1";
  if (!apiKey) {
    return new Response(JSON.stringify({ error: "Missing DASHSCOPE_API_KEY" }), { status: 500 });
  }

  // Build messages: include image if provided
  const messages = imageDataUrl
    ? [{
        role: "user",
        content: [
          { type: "text", text: message },
          { type: "image_url", image_url: imageDataUrl }
        ]
      }]
    : [{ role: "user", content: message }];

  const upstream = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: "qwen3-omni-flash",
      messages,
      stream: true,
      stream_options: { include_usage: true },
      modalities: ["text", "audio"],
      audio: { voice: "Cherry", format: "wav" }
    })
  });

  if (!upstream.ok || !upstream.body) {
    const txt = await upstream.text().catch(() => "");
    return new Response(JSON.stringify({ error: `Upstream error ${upstream.status}`, detail: txt }), { status: 502 });
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const reader = upstream.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            if (trimmed.startsWith("data:")) {
              const payload = trimmed.slice(5).trim();
              if (payload === "[DONE]") continue;
              try {
                const json: UpstreamChunk = JSON.parse(payload);
                const delta = json.choices?.[0]?.delta;
                const out: { textDelta?: string; audioBase64Delta?: string } = {};
                if (delta?.content) out.textDelta = delta.content;
                if (delta?.audio?.data) out.audioBase64Delta = delta.audio.data;
                controller.enqueue(encoder.encode(JSON.stringify(out) + "\n"));
              } catch {}
            }
          }
        }
      } catch (e) {
        // swallow
      } finally {
        controller.close();
      }
    }
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-cache"
    }
  });
}

