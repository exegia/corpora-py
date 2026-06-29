import { Card, ScrollShadow, SearchField, Typography } from "@heroui/react";
import { Form, useParams } from "react-router";

export function meta() {
	return [{ title: "Corpus viewer · Corpora" }];
}

export default function CorpusView() {
	const { id } = useParams();

	return (
		<div className="flex flex-col gap-4">
			{/* Search uses Form method="get" so the query lives in the URL. */}
			<Form method="get">
				<SearchField name="q" className="w-full max-w-md" aria-label="Search corpus">
					<SearchField.Group>
						<SearchField.SearchIcon />
						<SearchField.Input placeholder={`Search ${id}…`} />
						<SearchField.ClearButton />
					</SearchField.Group>
				</SearchField>
			</Form>

			<Card>
				<Card.Content>
					<ScrollShadow className="max-h-[60vh]">
						<div className="flex flex-col gap-3 p-1">
							{/* TODO: render passages/results from a loader. */}
							<Typography type="body" className="text-neutral-500">
								Viewer for corpus “{id}”. Text content will render here once data
								loading is wired up.
							</Typography>
							{Array.from({ length: 8 }).map((_, i) => (
								<p key={i} className="text-sm leading-relaxed text-neutral-400">
									Placeholder passage {i + 1}.
								</p>
							))}
						</div>
					</ScrollShadow>
				</Card.Content>
			</Card>
		</div>
	);
}
