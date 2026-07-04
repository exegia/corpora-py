import { Button, Card, Surface, Typography } from "@heroui/react";
import { Icon } from "@iconify/react";
import { useNavigate } from "react-router";

export function meta() {
	return [{ title: "Corpora" }];
}

export default function Home() {
	const navigate = useNavigate();

	return (
		<div className="mx-auto flex w-full max-w-md flex-col gap-6">
			<Surface
				className="rounded-2xl border-2 border-neutral-100 p-6 dark:border-neutral-800"
				variant="default"
			>
				<Typography type="h2">Login</Typography>
				<div className="mt-4 flex flex-col gap-3">
					<Button className="w-full" variant="tertiary">
						<Icon icon="devicon:google" />
						Sign in with Google
					</Button>
					<Button className="w-full" variant="tertiary">
						<Icon icon="ion:logo-apple" />
						Sign in with Apple
					</Button>
				</div>
			</Surface>

			<Card variant="transparent">
				<Card.Header>
					<Card.Title>Get started</Card.Title>
					<Card.Description>
						Upload an existing corpus or convert a source document.
					</Card.Description>
				</Card.Header>
				<Card.Footer className="flex gap-2">
					<Button variant="primary" onPress={() => navigate("/corpus/upload")}>
						Upload corpus
					</Button>
					<Button variant="secondary" onPress={() => navigate("/corpus/convert")}>
						Convert source
					</Button>
				</Card.Footer>
			</Card>
		</div>
	);
}
