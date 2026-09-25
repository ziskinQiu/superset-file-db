/** Test stand-in for @apache-superset/core (aliased in vitest.config.ts). */

export const registrations: Array<unknown[]> = [];

export const views = {
  registerView(...args: unknown[]): void {
    registrations.push(args);
  },
};
