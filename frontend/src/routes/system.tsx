import { createFileRoute } from "@tanstack/react-router";
import { System } from "@/components/aegis/workspaces";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/system")({
  head: () => ({
    meta: [
      ...pageSeo("/system").meta,
      { title: "System | AEGIS Trust Console" },
      {
        name: "description",
        content: "Inspect AEGIS service connectivity and operational health.",
      },
      { property: "og:title", content: "System | AEGIS Trust Console" },
      {
        property: "og:description",
        content: "Inspect AEGIS service connectivity and operational health.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: pageSeo("/system").links,
  }),
  component: System,
});
