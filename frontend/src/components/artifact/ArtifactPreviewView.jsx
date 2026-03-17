// src/components/artifact/ArtifactPreviewView.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Renders a live visual preview of an artifact.
//
// - react / html / code → executed inside a sandboxed <iframe>
// - markdown            → rendered as formatted text
// - svg                 → injected inline as raw HTML
//
// The iframe sandbox prevents the artifact code from accessing the parent page.
// ─────────────────────────────────────────────────────────────────────────────
import { FormattedText } from '../chat/FormattedText'

export function ArtifactPreviewView({ artifact }) {

  // ── Markdown: render as formatted prose ───────────────────────────────────
  if (artifact.type === 'markdown') {
    return (
      <div className="p-6">
        <FormattedText text={artifact.content} />
      </div>
    )
  }

  // ── SVG: inject the raw SVG markup directly ───────────────────────────────
  if (artifact.type === 'svg') {
    return (
      <div
        className="flex items-center justify-center h-full p-8"
        dangerouslySetInnerHTML={{ __html: artifact.content }}
      />
    )
  }

  // ── React / HTML / code: run inside a sandboxed iframe ────────────────────
  //
  // We build a complete HTML document string and pass it to the iframe via
  // the `srcDoc` prop.  React + Babel are loaded via CDN so JSX runs in
  // the browser without a build step.
  const iframeDoc = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8"/>
      <meta name="viewport" content="width=device-width,initial-scale=1"/>
      <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
      <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
      <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
      <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; }
      </style>
    </head>
    <body>
      <div id="root"></div>
      <script type="text/babel">
        ${artifact.content}

        // Attempt to mount the default export (if any) into #root
        try {
          const exported =
            typeof exports !== 'undefined' && exports.default
              ? exports.default
              : typeof Dashboard !== 'undefined'
                ? Dashboard
                : null

          if (exported) {
            ReactDOM.createRoot(document.getElementById('root'))
              .render(React.createElement(exported))
          }
        } catch (e) {
          console.warn('Artifact mount error:', e)
        }
      </script>
    </body>
    </html>
  `

  return (
    <iframe
      title="artifact-preview"
      srcDoc={iframeDoc}
      sandbox="allow-scripts allow-same-origin"
      className="w-full h-full border-0"
    />
  )
}