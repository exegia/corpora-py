import { Button, Card, Separator, Typography } from "@heroui/react";
import { useNavigate, useParams } from "react-router";

export function meta() {
	return [{ title: "Corpus detail · Corpora" }];
}

const META_ROWS = [
	{ label: "Identifier", value: "—" },
	{ label: "Format", value: "Text-Fabric" },
	{ label: "Nodes", value: "—" },
	{ label: "Features", value: "—" },
];

export default function CorpusDetail() {
	const { id } = useParams();
	const navigate = useNavigate();

	return (
		<div className="flex flex-col gap-6">
			<Card>
				<Card.Header>
					<Card.Title>Overview</Card.Title>
					<Card.Description>Metadata for corpus “{id}”.</Card.Description>
				</Card.Header>
				<Card.Content>
					<dl className="flex flex-col">
						{META_ROWS.map((row, i) => (
							<div key={row.label}>
								{i > 0 && <Separator className="my-2" />}
								<div className="flex items-center justify-between text-sm">
									<dt className="text-neutral-500">{row.label}</dt>
									<dd>{row.value}</dd>
								</div>
							</div>
						))}
					</dl>
				</Card.Content>
				<Card.Footer>
					<Button
						variant="primary"
						onPress={() => navigate(`/corpus/${id}/view`)}
					>
						Open viewer
					</Button>
				</Card.Footer>
			</Card>

			<Typography type="body" className="text-neutral-500">
				{/* TODO: load real corpus metadata via a loader. */}
				Detail content is a placeholder pending data wiring.
			</Typography>
		</div>
	);
}
