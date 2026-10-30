const NAME_MAX = 100;

export function movedName(name: string, server: string): string {
  return server === '' ? name : `${name} (${server})`.slice(0, NAME_MAX);
}
