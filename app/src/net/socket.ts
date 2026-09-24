/** Future phase owns net/socket. */
export function unavailable(): never {
  throw new Error("unimplemented:net/socket");
}
