declare module "@apache-superset/core" {
  export const views: {
    registerView(
      view: { id: string; name: string },
      position: string,
      component: () => unknown
    ): void;
  };
}
