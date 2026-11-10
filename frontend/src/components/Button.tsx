import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: 'primary' | 'ghost'
  children: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { tone = 'primary', className = '', type = 'button', children, ...props },
  ref,
) {
  const toneClass = tone === 'primary' ? 'btn-primary' : 'btn-ghost'
  return (
    <button ref={ref} type={type} className={`btn ${toneClass} ${className}`} {...props}>
      {children}
    </button>
  )
})
