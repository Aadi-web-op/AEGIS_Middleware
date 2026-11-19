import { createFileRoute } from "@tanstack/react-router";
import { DataWorkspace } from "@/components/aegis/workspaces";
export const Route = createFileRoute("/intelligence")({
  head: () => ({
    meta: [
      { title: "Cross-decision intelligence | AEGIS Trust Console" },
      {
        name: "description",
        content: "Investigate recurring reliability patterns across AI decisions.",
      },
      { property: "og:title", content: "Cross-decision intelligence | AEGIS Trust Console" },
      {
        property: "og:description",
        content: "Investigate recurring reliability patterns across AI decisions.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <DataWorkspace kind="intelligence" />,
});
