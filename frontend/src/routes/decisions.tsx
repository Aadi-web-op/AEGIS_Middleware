import { createFileRoute } from "@tanstack/react-router";
import { DataWorkspace } from "@/components/aegis/workspaces";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/decisions")({
  head: () => ({
    meta: [
      ...pageSeo("/decisions").meta,
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
    links: pageSeo("/decisions").links,
  }),
  component: () => <DataWorkspace kind="decisions" />,
});
