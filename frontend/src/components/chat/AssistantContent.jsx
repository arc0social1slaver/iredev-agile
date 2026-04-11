// src/components/chat/AssistantContent.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Renders the body of an assistant message.
// Splits the raw text string into code blocks and formatted prose sections,
// then delegates to <CodeBlock> and <FormattedText> for each part.
// Also shows a blinking cursor at the end while the message is still streaming.
// ─────────────────────────────────────────────────────────────────────────────
import { CodeBlock } from "./CodeBlock";
import { FormattedText } from "./FormattedText";

export function AssistantContent({ content, streaming }) {
  // Split the content string by fenced code blocks: ```...```
  // The capturing group means the delimiters are kept in the resulting array.
  const parts = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className="space-y-3">
      {parts.map((part, i) => {
        // ── Fenced code block ────────────────────────────────────────────
        if (part.startsWith("```") && part.endsWith("```")) {
          // First line after the opening ``` is the language identifier
          const inner = part.slice(3, -3); // strip the backticks
          const newline = inner.indexOf("\n");
          const language = newline > -1 ? inner.slice(0, newline).trim() : "";
          const code = newline > -1 ? inner.slice(newline + 1) : inner;
          return <CodeBlock key={i} language={language} code={code} />;
        }

        const trimmed = part.trim();
        if (
          (trimmed.startsWith("[") && trimmed.endsWith("]")) ||
          (trimmed.startsWith("{") && trimmed.endsWith("}"))
        ) {
          try {
            // Validate it's actually valid JSON
            JSON.parse(trimmed);
            return <CodeBlock key={i} language="json" code={trimmed} />;
          } catch (e) {
            // Not valid JSON → treat as normal text
          }
        }

        // ── Regular prose (headings, bullets, bold, etc.) ────────────────
        return part.trim() ? <FormattedText key={i} text={part} /> : null;
      })}

      {/* Blinking cursor shown at the end while the response is streaming */}
      {streaming && <span className="cursor" />}
    </div>
  );
}
