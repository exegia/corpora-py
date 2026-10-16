"use client"

import { SegmentGroup as ArkSegmentGroup, useSegmentGroupContext } from "@ark-ui/react/segment-group"
import type React from "react"
import { cn } from "@/lib/utils"
import { Glass, type GlassOptics } from "@samasante/liquid-glass"

export const useSegmentGroup = useSegmentGroupContext

type SegmentGroupVariant = "default" | "underline"

interface SegmentGroupProps extends React.ComponentProps<typeof ArkSegmentGroup.Root> {
    /**
     * The visual variant of the segment group.
     *
     * @default "default"
     */
    variant?: SegmentGroupVariant
    glassOptics?: Partial<GlassOptics>
}

export const SegmentGroup = (props: SegmentGroupProps) => {
    const { orientation = "horizontal", variant = "default", className, children, glassOptics, ...rest } = props

    return (
        <ArkSegmentGroup.Root
            className={cn(
                "group/segment-group relative rounded-lg",
                "flex gap-2",
                "isolate",
                "data-[orientation=vertical]:flex-col",
                "data-disabled:opacity-64",
                "data-[variant=underline]:gap-1 data-[variant=underline]:border-input",
                "data-[orientation=horizontal]:data-[variant=underline]:border-b",
                "data-[orientation=vertical]:data-[variant=underline]:border-l",
                className
            )}
            data-slot="segment-group"
            data-variant={variant}
            orientation={orientation}
            {...rest}>
            <SegmentGroupIndicator optics={glassOptics} />

            {children}
        </ArkSegmentGroup.Root>
    )
}

export const SegmentGroupItem = (props: React.ComponentProps<typeof ArkSegmentGroup.Item>) => {
    const { className, children, ...rest } = props

    return (
        <ArkSegmentGroup.Item
            className={cn(
                "relative",
                "cursor-pointer",
                "data-[orientation=vertical]:w-full data-[orientation=vertical]:justify-start",
                "rounded-[inherit] border border-transparent",
                "outline-none data-focus-visible:border-primary data-focus-visible:ring-[3px] data-focus-visible:ring-ring/32",
                "data-disabled:pointer-events-none data-disabled:opacity-64",
                className
            )}
            data-slot="segment-group-item"
            {...rest}>
            {children}

            <ArkSegmentGroup.ItemControl />
            <ArkSegmentGroup.ItemHiddenInput />
        </ArkSegmentGroup.Item>
    )
}

export const SegmentGroupItemText = (props: React.ComponentProps<typeof ArkSegmentGroup.ItemText>) => {
    const { className, ...rest } = props

    return (
        <ArkSegmentGroup.ItemText
            className={cn("relative z-1", className)}
            data-slot="segment-group-item-text"
            {...rest}
        />
    )
}

interface SegmentGroupIndicatorProps extends React.ComponentProps<typeof ArkSegmentGroup.Indicator> {
    optics?: Partial<GlassOptics>
}

export const SegmentGroupIndicator = (props: SegmentGroupIndicatorProps) => {
    const { className, optics, ...rest } = props

    return (
        <ArkSegmentGroup.Indicator
            className={cn(
                "pointer-events-none absolute top-(--top) left-(--left) z-0",
                "h-(--height) w-(--width)",
                "rounded-[inherit]",
                "bg-white/15 dark:bg-input",
                "shadow-[0_1px_2px_rgb(15_23_42/0.1),inset_0_-1px_0_rgb(15_23_42/0.12)] dark:shadow-none",
                "transition-[width,height,left,top] duration-150 ease-out",
                "[transition-property:var(--transition-property,width,height,left,top)]",
                "group-data-[variant=underline]/segment-group:bg-primary",
                "data-[orientation=horizontal]:group-data-[variant=underline]/segment-group:top-[calc(var(--top)+var(--height)-1px)]",
                "data-[orientation=vertical]:group-data-[variant=underline]/segment-group:right-[calc(var(--left)+var(--width)-1px)]",
                "data-[orientation=vertical]:group-data-[variant=underline]/segment-group:-translate-x-px",
                "data-[orientation=horizontal]:group-data-[variant=underline]/segment-group:h-0.5",
                "data-[orientation=vertical]:group-data-[variant=underline]/segment-group:w-0.5",
                "motion-reduce:transition-none!",
                className
            )}
            data-slot="segment-group-indicator"
            {...rest}>
            <Glass
                className="absolute inset-0 size-full rounded-[inherit]"
                radius={8}
                optics={optics}
                aria-hidden="true">
                <span aria-hidden="true" />
            </Glass>
        </ArkSegmentGroup.Indicator>
    )
}
