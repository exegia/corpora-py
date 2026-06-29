import { Surface, Typography, Button } from '@heroui/react';
import {Icon} from "@iconify/react";

function App() {

	return (
	<main className="flex min-h-screen items-center justify-center select-none bg-neutral-100 dark:bg-neutral-900">
      <Surface className='p-6 border-2 border-neutral-100 rounded-2xl w-1/3' variant="default">


        <Typography type="h2">Login</Typography>
        <div className="flex flex-col gap-3 mt-4">
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
			</main>
	);
}

export default App;
