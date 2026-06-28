import { Breadcrumbs, Chip, Typography } from "@heroui/react";
import { NavLink, Outlet, useParams } from "react-router";

export default function CorpusLayout() {
	const { id } = useParams();

	const tabs = [
		{ to: `/corpus/${id}`, label: "Detail", end: true },
		{ to: `/corpus/${id}/view`, label: "View", end: false },
	];

	return (
		<div className="mx-auto w-full max-w-4xl">
			<Breadcrumbs>
				<Breadcrumbs.Item href="/">Home</Breadcrumbs.Item>
				<Breadcrumbs.Item>Corpus</Breadcrumbs.Item>
				<Breadcrumbs.Item>{id}</Breadcrumbs.Item>
			</Breadcrumbs>

			<div className="mt-3 flex items-center gap-3">
				<Typography type="h2">{id}</Typography>
				<Chip variant="secondary" size="sm">
					corpus
				</Chip>
			</div>

			<nav className="mt-4 flex gap-1 border-b border-neutral-200 dark:border-neutral-800">
				{tabs.map(({ to, label, end }) => (
					<NavLink
						key={label}
						to={to}
						end={end}
						className={({ isActive }) =>
							`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
								isActive
									? "border-neutral-800 font-medium dark:border-neutral-200"
									: "border-transparent text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
							}`
						}
					>
						{label}
					</NavLink>
				))}
			</nav>

			<div className="py-6">
				<Outlet />
			</div>
		</div>
	);
}
