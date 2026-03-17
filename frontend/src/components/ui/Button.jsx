// src/components/ui/Button.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Generic reusable button with three visual variants and four sizes.
//
// Usage:
//   <Button variant="primary" size="md" onClick={...}>Save</Button>
//   <Button variant="ghost"   size="icon"><Icon /></Button>
// ─────────────────────────────────────────────────────────────────────────────

// src/components/ui/Button.jsx
// Generic button matching Claude's exact interactive styles.

export function Button({
  children,
  variant  = 'ghost',
  size     = 'md',
  onClick,
  disabled,
  className = '',
  type = 'button',
}) {
  const base =
    'inline-flex items-center justify-center font-medium rounded-lg ' +
    'transition-colors duration-100 focus:outline-none ' +
    'disabled:opacity-40 disabled:pointer-events-none select-none'

  const variants = {
    // Solid terracotta — send button, primary CTAs
    primary:
      'bg-[#C96A42] hover:bg-[#B85E38] text-white',

    // No background, subtle hover fill — icon buttons, nav items
    ghost:
      'text-[#3D3530] hover:bg-[#EAE6DC] hover:text-[#1A1410]',

    // Light border — secondary actions
    outline:
      'border border-[#E8E3D9] text-[#3D3530] ' +
      'hover:bg-[#EAE6DC] hover:border-[#D9D3C8]',
  }

  const sizes = {
    sm:   'h-7  px-2.5 text-xs  gap-1.5',
    md:   'h-8  px-3   text-sm  gap-1.5',
    lg:   'h-9  px-4   text-sm  gap-2',
    icon: 'h-7  w-7',
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {children}
    </button>
  )
}