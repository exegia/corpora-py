import { PyBridge } from 'pybridge';
import "bun";


interface API {
    word_sizes(words: string[]): number[];
}


export async function wordSizes(words: string[]): Promise<number[]> {
  const bridge = new PyBridge({ python: 'python3', cwd: __dirname });
  try {
    const api = bridge.controller<API>('script.py');
    return await api.word_sizes(words);
  } finally {
    bridge.close();
  }
}
