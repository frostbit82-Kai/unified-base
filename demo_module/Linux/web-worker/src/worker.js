// A module worker: it can `import`, and Vite bundles it like any other entry.
import { sieve, tail } from './sieve.js';

self.onmessage = (e) => {
  const { limit } = e.data;
  const t0 = performance.now();
  const { count, flags } = sieve(limit);
  const ms = performance.now() - t0;

  // Hand the buffer over instead of copying it: after this postMessage the
  // worker's view is detached (byteLength 0) and the page owns the memory.
  self.postMessage(
    { count, ms, limit, largest: tail(flags, limit), buffer: flags.buffer },
    [flags.buffer]
  );
};
