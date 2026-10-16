/** True for the error a browser raises when a lazily loaded chunk is missing - typically a tab
 *  left open across a new deploy, whose old file names no longer exist. */
export function isChunkLoadError(error: unknown): boolean {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /dynamically imported module|Importing a module script failed|ChunkLoadError|Loading chunk|module script/i.test(
    text,
  );
}
