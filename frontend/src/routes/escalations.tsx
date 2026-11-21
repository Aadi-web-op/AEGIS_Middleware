import { createFileRoute } from "@tanstack/react-router";
import { DataWorkspace } from "@/components/aegis/workspaces";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/escalations")({
  head: () => ({
    meta: [
      ...pageSeo("/escalations").meta,
      { title: "Escalations | AEGIS Trust Console" },
      { name: "description", content: "Review human escalations with evidence and claim context." },
      { property: "og:title", content: "Escalations | AEGIS Trust Console" },
      {
        property: "og:description",
        content: "Review human escalations with evidence and claim context.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: pageSeo("/escalations").links,
  }),
  component: () => <DataWorkspace kind="escalations" />,
});
