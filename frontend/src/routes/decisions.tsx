import { createFileRoute } from "@tanstack/react-router";
import { DataWorkspace } from "@/components/aegis/workspaces";
export const Route = createFileRoute("/decisions")({
  head: () => ({
    meta: [
      { title: "Decisions | AEGIS Trust Console" },
      { name: "description", content: "Investigate historical AI decisions and their evidence." },
      { property: "og:title", content: "Decisions | AEGIS Trust Console" },
      {
        property: "og:description",
        content: "Investigate historical AI decisions and their evidence.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: () => <DataWorkspace kind="decisions" />,
});
