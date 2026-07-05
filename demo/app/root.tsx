import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration
} from "react-router"
import { useTheme } from "@heroui/react"
import { TopNav, TopNavHeading, TopNavItem } from "@astryxdesign/core/TopNav"
import { LayerProvider } from "@astryxdesign/core/Layer"

import "./app.css"

import { StatusBar } from "./components"
import React, { useEffect } from "react"
import { AppShell } from "@astryxdesign/core/AppShell"
import { NavIcon, SideNav, SideNavItem, SideNavSection } from "@astryxdesign/core"
import { ChartBarIcon, FolderIcon, HomeIcon, SettingsIcon, UsersIcon } from "lucide-react"
import { VStack } from "@astryxdesign/core/VStack"

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/corpus/upload", label: "Upload", end: false },
  { to: "/corpus/convert", label: "Convert", end: false },
  { to: "./logs", label: "Logs", end: true }
]

export function TopNavigation() {

  return (
    <TopNav
      label="Main navigation"
      heading={<TopNavHeading heading="App" />}
      startContent={
        <>
          {
            NAV.map((navItem) => (
              <TopNavItem key={navItem.label} label={navItem.label} href={navItem.to} />
            ))
          }
        </>
      }
    />
  )
}

// Global document shell — everything renders inside this.
export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
    <head>
      <meta charSet="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <link rel="icon" href="data:image/x-icon;base64,AA" />
      <Meta />
      <Links />
      <title>Corpora | Admin</title>
    </head>
    <body className="min-h-screen bg-neutral-100 dark:bg-taupe-950">
    <LayerProvider>
      {children}
      <ScrollRestoration />
    </LayerProvider>
    <Scripts />
    </body>
    </html>
  )
}

export const AppShellWrapper = ({ children }: { children: React.ReactNode }) => {
  return (
    <AppShell
      contentPadding={6}
      style={{ height: "100%", minHeight: 0 }}
      topNav={
        <TopNav
          label="Main navigation"
          heading={
            <TopNavHeading
              heading="App Shell"
              logo={
                <NavIcon icon={"s"} />
              }
            />
          }
          startContent={
            <>
              <TopNavItem label="Home" href="#" isSelected />
              <TopNavItem label="Products" href="#" />
              <TopNavItem label="Docs" href="#" />
            </>
          }
        />
      }
      sideNav={
        <SideNav>
          <SideNavSection title="Main" isHeaderHidden>
            <SideNavItem
              label="Dashboard"
              icon={HomeIcon}
              isSelected
              href="#"
            />
            <SideNavItem label="Analytics" icon={ChartBarIcon} href="#" />
            <SideNavItem label="Projects" icon={FolderIcon} href="#" />
          </SideNavSection>
          <SideNavSection title="Organization">
            <SideNavItem label="Team" icon={UsersIcon} href="#" />
            <SideNavItem label="Settings" icon={SettingsIcon} href="#" />
          </SideNavSection>
        </SideNav>
      }>
      <VStack gap={4}>
        {children}
      </VStack>
    </AppShell>
  )
}

// Global UI (nav) lives in the root per framework-mode conventions.
export default function App() {

  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
  const { setTheme } = useTheme(mediaQuery.matches ? "dark" : "light")

  useEffect(() => {
    setTheme(mediaQuery.matches ? "dark" : "light")
  }, [])
  useEffect(() => {
    mediaQuery.addEventListener("change", event => setTheme(event.matches ? "dark" : "light"))
  }, [mediaQuery.matches])

  return (
    <div className="flex min-h-screen flex-col relative select-none">

      <div
        className="electrobun-webkit-app-region-drag w-full flex flex-col  justify-center py-1.5 fixed top-0 border-b border-tertiary/10 z-50  backdrop-blur-xl h-12">
        <TopNavigation />
      </div>

      <main className="flex-1 px-6 py-8 flex flex-col justify-center relative bg-background-secondary">
        <Outlet />
        <StatusBar />
      </main>
    </div>
  )
}
