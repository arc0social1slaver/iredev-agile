// src/components/layout/MainLayout.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Top-level layout shell.
// Renders a full-height flex row that hosts the three main regions:
//   [ Sidebar ] [ Chat area ] [ Artifact panel (optional) ]
//
// All sizing decisions live here so child components stay layout-agnostic.
// ─────────────────────────────────────────────────────────────────────────────

export function MainLayout({ children }) {
  return (
    <div className="flex h-screen overflow-hidden bg-[#F4F0E6]">
      {children}
    </div>
  )
}
