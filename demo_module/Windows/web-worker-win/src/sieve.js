// The workload, imported by BOTH the worker and the main thread so the two
// paths run byte-identical code — the only difference is which thread it's on.
export function sieve(limit) {
  // Uint8Array over a plain array: one byte per candidate, and the buffer can
  // be transferred to another thread with zero copying.
  const flags = new Uint8Array(limit + 1);
  let count = 0;
  for (let n = 2; n <= limit; n++) {
    if (flags[n]) continue;
    count++;
    for (let m = n * n; m <= limit; m += n) flags[m] = 1;
  }
  return { count, flags };
}

/** Largest primes found, for something concrete to show. */
export function tail(flags, limit, howMany = 5) {
  const out = [];
  for (let n = limit; n >= 2 && out.length < howMany; n--) {
    if (!flags[n]) out.push(n);
  }
  return out.reverse();
}
