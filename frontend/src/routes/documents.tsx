import { createFileRoute } from "@tanstack/react-router";
import { DataWorkspace } from "@/components/aegis/workspaces";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/documents")({
  head: () => ({
    meta: [
      ...pageSeo("/documents").meta,
      { title: "Documents | AEGIS Trust Console" },
      { name: "description", content: "Inspect source freshness, conflicts, and decision impact." },
      { property: "og:title", content: "Documents | AEGIS Trust Console" },
      {
        property: "og:description",
        content: "Inspect source freshness, conflicts, and decision impact.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: pageSeo("/documents").links,
  }),
  component: () => <DataWorkspace kind="documents" />,
});
