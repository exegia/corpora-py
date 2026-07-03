import {
	Links,
	Meta,
	NavLink,
	Outlet,
	Scripts,
	ScrollRestoration,
  useNavigate,
} from "react-router";
import { Typography, useTheme } from "@heroui/react";

import "./app.css";

const NAV = [
	{ to: "/", label: "Home", end: true },
	{ to: "/corpus/upload", label: "Upload", end: false },
  { to: "/corpus/convert", label: "Convert", end: false },
	{ to: "./logs", label: "Logs", end: true }
];

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
			</head>
			<body className="min-h-screen bg-neutral-100 dark:bg-taupe-950">
				{children}
				<ScrollRestoration />
				<Scripts />
			</body>
		</html>
	);
}

// Global UI (nav) lives in the root per framework-mode conventions.
export default function App() {
  const navigate = useNavigate()
  const {} = useTheme("system")
	return (
    <div className="flex min-h-screen flex-col relative select-none">

      <div className="electrobun-webkit-app-region-drag w-full flex flex-col  justify-center py-1.5 fixed top-0 border-b border-tertiary/10 z-50  backdrop-blur-xl h-12">
					<Typography type="body-sm" className="font-bold text-center">Corpora</Typography>
      </div>

      <main className="flex-1 px-6 py-8 flex flex-col justify-center relative bg-background-secondary">
          <Outlet />
			</main>
		</div>
	);
}
