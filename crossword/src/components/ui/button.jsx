import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-neutral-950 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-neutral-900 text-neutral-50 shadow hover:bg-neutral-900/90',
        destructive: 'bg-red-500 text-neutral-50 shadow-sm hover:bg-red-500/90',
        outline: 'border border-neutral-200 bg-white shadow-sm hover:bg-neutral-100 hover:text-neutral-900',
        ghost: 'hover:bg-neutral-100 hover:text-neutral-900',
      },
      size: {
        default: 'h-8 px-3 py-1',
        sm: 'h-7 px-2 text-xs',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button'
  return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
})
Button.displayName = 'Button'

export { Button, buttonVariants }
