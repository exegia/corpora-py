import {
	Button,
	Card,
	Description,
	Input,
	Label,
	TextArea,
	TextField,
	Typography,
} from "@heroui/react";
import { Form } from "react-router";

export function meta() {
	return [{ title: "Upload corpus · Corpora" }];
}

export default function CorpusUpload() {
	return (
		<div className="mx-auto w-full max-w-xl">
			<Typography type="h2">Upload corpus</Typography>
			<Typography type="body" className="mt-1 text-neutral-500">
				Add an existing Text-Fabric dataset to your library.
			</Typography>

			<Card className="mt-6">
				<Card.Content>
					{/* TODO: wire an `action` to receive the upload (multipart). */}
					<Form method="post" encType="multipart/form-data" className="flex flex-col gap-5">
						<TextField name="name" isRequired>
							<Label>Corpus name</Label>
							<Input placeholder="e.g. BHSA" />
							<Description>A short, unique identifier for the corpus.</Description>
						</TextField>

						<TextField name="description">
							<Label>Description</Label>
							<TextArea placeholder="What does this corpus contain?" rows={3} />
						</TextField>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="file">Dataset archive</Label>
							<input
								id="file"
								name="file"
								type="file"
								accept=".zip,.tar,.gz,.tgz"
								className="text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-neutral-200 file:px-3 file:py-1.5 file:text-sm dark:file:bg-neutral-800"
							/>
						</div>

						<div className="flex justify-end gap-2">
							<Button type="reset" variant="tertiary">
								Reset
							</Button>
							<Button type="submit" variant="primary">
								Upload
							</Button>
						</div>
					</Form>
				</Card.Content>
			</Card>
		</div>
	);
}
