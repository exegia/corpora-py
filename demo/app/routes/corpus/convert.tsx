import {
	Button,
	Card,
	Description,
	Input,
	Label,
	ListBox,
	Select,
	TextField,
	Typography,
} from "@heroui/react";
import { Form } from "react-router";

export function meta() {
	return [{ title: "Convert source · Corpora" }];
}

const SOURCE_FORMATS = [
	{ id: "epub", label: "EPUB" },
	{ id: "html", label: "HTML" },
];

export default function CorpusConvert() {
	return (
		<div className="mx-auto w-full max-w-xl">
			<Typography type="h2">Convert source</Typography>
			<Typography type="body" className="mt-1 text-neutral-500">
				Convert an EPUB or HTML document into a Text-Fabric dataset.
			</Typography>

			<Card className="mt-6">
				<Card.Content>
					{/* TODO: wire an `action` to kick off the conversion pipeline. */}
					<Form method="post" encType="multipart/form-data" className="flex flex-col gap-5">
						<TextField name="name" isRequired>
							<Label>Corpus name</Label>
							<Input placeholder="e.g. my-book" />
							<Description>Name for the generated dataset.</Description>
						</TextField>

						<Select name="format" defaultSelectedKey="epub" className="w-full">
							<Label>Source format</Label>
							<Select.Trigger>
								<Select.Value />
								<Select.Indicator />
							</Select.Trigger>
							<Select.Popover>
								<ListBox>
									{SOURCE_FORMATS.map((fmt) => (
										<ListBox.Item key={fmt.id} id={fmt.id} textValue={fmt.label}>
											{fmt.label}
											<ListBox.ItemIndicator />
										</ListBox.Item>
									))}
								</ListBox>
							</Select.Popover>
						</Select>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="source">Source file</Label>
							<input
								id="source"
								name="source"
								type="file"
								accept=".epub,.html,.htm"
								className="text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-neutral-200 file:px-3 file:py-1.5 file:text-sm dark:file:bg-neutral-800"
							/>
						</div>

						<div className="flex justify-end gap-2">
							<Button type="reset" variant="tertiary">
								Reset
							</Button>
							<Button type="submit" variant="primary">
								Convert
							</Button>
						</div>
					</Form>
				</Card.Content>
			</Card>
		</div>
	);
}
