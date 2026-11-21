import { createFileRoute } from "@tanstack/react-router";
import { DataWorkspace } from "@/components/aegis/workspaces";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/intelligence")({
  head: () => ({
    meta: [
      ...pageSeo("/intelligence").meta,
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
    links: pageSeo("/intelligence").links,
  }),
  component: () => <DataWorkspace kind="intelligence" />,
});
