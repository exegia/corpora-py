// File: app.ts
import { PyBridge } from 'pybridge';
import "bun";


interface API {
    word_sizes(words: string[]): number[];
}


class PythonRuntime extends PyBridge {

  private load = () => {
    const bridge = new PyBridge({ python: 'python3', cwd: __dirname });
  }

}

const api = bridge.controller<API>('script.py');
const sizes = await api.word_sizes(['hello', 'world']);

expect(sizes).toEqual([5, 5]);

bridge.close();
