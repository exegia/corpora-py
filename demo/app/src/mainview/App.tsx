import { Surface } from '@heroui/react';
import { Typography } from "@heroui/react";
import {Icon} from "@iconify/react";
import { Button } from "@heroui/react";

function App() {

	return (
    <div>
      <Surface>
        <Typography>Login</Typography>
        <Button className="w-full" variant="tertiary">
              <Icon icon="devicon:google" />
              Sign in with Google
            </Button>
        <Button className="w-full" variant="tertiary">

              <Icon icon="ion:logo-apple" />
              Sign in with Apple
            </Button>

      </Surface>
			</div>
	);
}

export default App;
