import { createFileRoute } from "@tanstack/react-router";
import { DataWorkspace } from "@/components/aegis/workspaces";
export const Route = createFileRoute("/documents")({
  head: () => ({
    meta: [
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
  }),
  component: () => <DataWorkspace kind="documents" />,
});
