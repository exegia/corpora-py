"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { motion, type Variants } from "framer-motion"
import { cn } from "~/lib/utils"

const noiseBg =
  "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E\")"

const folderVariants: Variants = {
  closed: { rotateX: 0, scale: 1 },
  hover: {
    scale: 1.02,
    transition: { type: "spring", stiffness: 200, damping: 20, mass: 1 },
  },
  open: {
    scale: 1.1,
    transition: { type: "spring", stiffness: 150, damping: 18, mass: 1 },
  },
}

const lidVariants: Variants = {
  closed: {
    rotateX: -20,
    transition: { type: "spring", stiffness: 60, damping: 20 },
  },
  hover: {
    rotateX: -30,
    transition: { type: "spring", stiffness: 100, damping: 18, mass: 1 },
  },
  open: {
    rotateX: -60,
    transition: { type: "spring", stiffness: 90, damping: 18, mass: 1 },
  },
}

const paperVariants: Variants = {
  closed: (t: number) => ({
    y: -40 - 5 * t,
    x: 0,
    scale: 0.95,
    rotate: (t - 1) * 2,
    z: (2 - t) * 5,
    transition: { type: "spring", stiffness: 150, damping: 25, mass: 1 },
  }),
  hover: (t: number) => ({
    y: -70 - 5 * t,
    x: 0,
    rotate: (t - 1) * 4,
    scale: 0.95,
    z: (2 - t) * 5,
    transition: { type: "spring", stiffness: 140, damping: 18 },
  }),
  open: (t: number) => ({
    y: -160 + 10 * Math.abs(t - 1),
    x: (1 - t) * 120,
    rotate: -((t - 1) * 8),
    scale: 0.9,
    z: 200 + (2 - t) * 5,
    transition: {
      type: "spring",
      stiffness: 80,
      damping: 14,
      mass: 1,
      delay: 0.08 * t,
    },
  }),
}

function PaperContent({ index }: { index: number }) {
  if (index === 0) {
    return (
      <>
        <div className="mb-6 h-3 w-1/3 rounded-full bg-gray-900/10" />
        <div className="space-y-3 opacity-70">
          <div className="h-2 w-full rounded-full bg-gray-900/10" />
          <div className="h-2 w-5/6 rounded-full bg-gray-900/10" />
          <div className="mt-4 h-10 w-full rounded-lg border border-dashed border-gray-300/60 bg-gray-200/50" />
        </div>
      </>
    )
  }
  if (index === 1) {
    return (
      <>
        <div className="mb-6 flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-gray-200/80" />
          <div className="flex-1 space-y-1.5">
            <div className="h-2.5 w-1/2 rounded-full bg-gray-900/10" />
            <div className="h-2 w-1/3 rounded-full bg-gray-900/5" />
          </div>
        </div>
        <div className="space-y-3 opacity-70">
          <div className="h-2 w-full rounded-full bg-gray-900/10" />
          <div className="h-2 w-11/12 rounded-full bg-gray-900/10" />
          <div className="h-2 w-4/5 rounded-full bg-gray-900/10" />
          <div className="h-2 w-full rounded-full bg-gray-900/10" />
        </div>
      </>
    )
  }
  return (
    <>
      <div className="mb-6 h-3 w-1/2 rounded-full bg-gray-900/10" />
      <div className="mb-4 grid grid-cols-2 gap-3">
        <div className="h-16 rounded-md border border-gray-300/20 bg-gray-200/40" />
        <div className="h-16 rounded-md border border-gray-100 bg-gray-50" />
      </div>
      <div className="space-y-3 opacity-70">
        <div className="h-2 w-full rounded-full bg-gray-900/10" />
        <div className="h-2 w-2/3 rounded-full bg-gray-900/10" />
      </div>
    </>
  )
}

export default function GlassFolder({
  open,
  onHover,
  isHovered,
  className,
}: {
  onHover?: (value: boolean) => void
  className?: string
  isHovered: boolean
  open: boolean
}) {
  const [isOpen, setOpen] = useState(open)
  const [hover, setHover] = useState(isHovered)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  useEffect(() => {
    if (hover === isHovered) return
    setHover(isHovered)
  }, [isHovered])

  const state = isOpen ? "open" : hover ? "hover" : "closed"

  const handleOnHover = (value: boolean) =>
    useCallback(() => {
      setHover(value)
      if (onHover) onHover(value)
    }, [value, onHover])

  return (
    <div
      ref={ref}
      className={cn("group relative h-52 w-64", className)}
      style={{ perspective: "1200px" }}
    >
      {/* Contact shadow under the folder */}
      <div
        className="absolute right-8 -bottom-12 left-8 h-6 rounded-full bg-black/20 blur-2xl transition-transform duration-700 group-hover:scale-x-110"
        style={{ transform: "rotateX(90deg) translateZ(-80px)" }}
      />

      <motion.div
        className="relative h-full w-full cursor-pointer"
        variants={folderVariants}
        initial="closed"
        animate={state}
        onHoverStart={() => handleOnHover(true)}
        onHoverEnd={() => handleOnHover(false)}
        onClick={() => setOpen((o) => !o)}
        style={{ transformStyle: "preserve-3d" }}
      >
        {/* Folder body / back panel */}
        <div
          className="absolute inset-0 rounded-3xl shadow-xl"
          style={{
            transformStyle: "preserve-3d",
            background:
              "radial-gradient(circle at 50% 0%, #3a3a3a 0%, #1a1a1a 60%, #050505 100%)",
            boxShadow: `
              inset 0 1px 0 rgba(255,255,255,0.25),
              inset 1px 0 0 rgba(255,255,255,0.1),
              inset -1px 0 0 rgba(255,255,255,0.1),
              inset 0 -2px 5px rgba(0,0,0,0.8),
              inset 0 0 40px rgba(0,0,0,0.6),
              0 25px 50px -12px rgba(0,0,0,0.8)
            `,
            border: "2px solid rgba(255,255,255,0.05)",
            transform: "translateZ(-20px)",
          }}
        >
          <div
            className="pointer-events-none absolute inset-0 rounded-3xl opacity-[0.2] mix-blend-overlay"
            style={{ backgroundImage: noiseBg }}
          />
          <div className="absolute inset-0 rounded-3xl bg-linear-to-t from-black/90 via-black/80 to-transparent opacity-60" />
        </div>

        {/* Papers stacked inside the folder */}
        <div
          className="pointer-events-none absolute inset-x-5 top-4 bottom-4"
          style={{ transformStyle: "preserve-3d" }}
        >
          {[2, 1, 0].map((t) => (
            <motion.div
              key={t}
              custom={t}
              variants={paperVariants}
              className="absolute inset-x-0 bottom-0 flex h-44 flex-col overflow-hidden rounded-xl p-5"
              style={{
                transformOrigin: "bottom center",
                zIndex: 5 - t,
                background:
                  "linear-gradient(to bottom, #ffffff 0%, #f0f0f2 100%)",
                borderTop: "1px solid rgba(255,255,255,0.8)",
                borderLeft: "1px solid rgba(255,255,255,0.4)",
                borderRight: "1px solid rgba(255,255,255,0.4)",
                boxShadow: `
                  inset 0 0 20px rgba(255,255,255,0.5),
                  0 1px 2px rgba(0,0,0,0.05),
                  0 4px 8px rgba(0,0,0,0.05),
                  0 8px 24px -4px rgba(0,0,0,0.1)
                `,
              }}
            >
              <div
                className="pointer-events-none absolute inset-0 opacity-[0.06] mix-blend-multiply"
                style={{ backgroundImage: noiseBg }}
              />
              <div className="relative z-10">
                <PaperContent index={t} />
              </div>
              <div className="pointer-events-none absolute inset-0 bg-linear-to-br from-white/60 via-transparent to-black/2" />
            </motion.div>
          ))}
        </div>

        {/* Folder front cover / lid */}
        <motion.div
          variants={lidVariants}
          className="absolute inset-0"
          style={{ transformStyle: "preserve-3d", transformOrigin: "bottom" }}
        >
          <div
            className="absolute inset-x-0 bottom-0 h-[85%] overflow-hidden rounded-3xl transition-all duration-500"
            style={{
              background:
                "linear-gradient(145deg, rgba(30,30,30,0.8) 0%, rgba(5,5,5,0.85) 100%)",
              backdropFilter: "blur(4px)",
              WebkitBackdropFilter: "blur(4px)",
              boxShadow: `
                inset 0 1px 0 rgba(255,255,255,0.15),
                inset 1px 0 0 rgba(255,255,255,0.08),
                inset -1px 0 0 rgba(255,255,255,0.05),
                0 -5px 20px rgba(0,0,0,0.3)
              `,
              borderTop: "1px solid rgba(255,255,255,0.4)",
            }}
          >
            <div className="pointer-events-none absolute -inset-full translate-y-1/3 rotate-0 transform bg-linear-to-tr from-transparent via-white/5 to-transparent transition-transform duration-700 group-hover:translate-y-0" />
            <div
              className="pointer-events-none absolute inset-0 opacity-[0.5] mix-blend-overlay"
              style={{ backgroundImage: noiseBg }}
            />
          </div>
        </motion.div>
      </motion.div>
    </div>
  )
}
