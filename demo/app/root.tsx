import {
	Links,
	Meta,
	NavLink,
	Outlet,
	Scripts,
	ScrollRestoration,
} from "react-router";
import { Typography } from "@heroui/react";

import "./app.css";

const NAV = [
	{ to: "/", label: "Home", end: true },
	{ to: "/corpus/upload", label: "Upload", end: false },
	{ to: "/corpus/convert", label: "Convert", end: false },
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
			<body className="min-h-screen bg-neutral-100 dark:bg-neutral-900">
				{children}
				<ScrollRestoration />
				<Scripts />
			</body>
		</html>
	);
}

// Global UI (nav) lives in the root per framework-mode conventions.
export default function App() {
	return (
    <div className="flex min-h-screen flex-col relative">
      <div className="electrobun-webkit-app-region-drag w-full flex justify-center py-1.5 absolute left-0 top-0 select-none">
        <Typography type="h6">Corpora</Typography>
      </div>
			<header className="flex items-center gap-6 border-b border-neutral-200 px-6 py-3 dark:border-neutral-800 mt-6">
				<NavLink to="/" className="no-underline">
					<Typography type="h4">Corpora</Typography>
				</NavLink>
				<nav className="flex items-center gap-1">
					{NAV.map(({ to, label, end }) => (
						<NavLink
							key={to}
							to={to}
							end={end}
							className={({ isActive }) =>
								`rounded-lg px-3 py-1.5 text-sm transition-colors ${
									isActive
										? "bg-neutral-200 font-medium dark:bg-neutral-800"
										: "text-neutral-600 hover:bg-neutral-200/60 dark:text-neutral-400 dark:hover:bg-neutral-800/60"
								}`
							}
						>
							{label}
						</NavLink>
					))}
				</nav>
			</header>

			<main className="flex-1 px-6 py-8 h-full flex flex-col justify-center">
				<Outlet />
			</main>
		</div>
	);
}
