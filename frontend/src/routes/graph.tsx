import { createFileRoute } from "@tanstack/react-router";
import { Graph } from "@/components/aegis/workspaces";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/graph")({
  head: () => ({
    meta: [
      ...pageSeo("/graph").meta,
      { title: "Graph explorer | AEGIS Trust Console" },
      { name: "description", content: "Explore the Neo4j evidence and decision graph." },
      { property: "og:title", content: "Graph explorer | AEGIS Trust Console" },
      { property: "og:description", content: "Explore the Neo4j evidence and decision graph." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: pageSeo("/graph").links,
  }),
  component: Graph,
});
