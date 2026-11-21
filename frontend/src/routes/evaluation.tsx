import { createFileRoute } from "@tanstack/react-router";
import { Evaluation } from "@/components/aegis/workspaces";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/evaluation")({
  head: () => ({
    meta: [
      ...pageSeo("/evaluation").meta,
      { title: "Live evaluation | AEGIS Trust Console" },
      { name: "description", content: "Verify AI answers against real evidence." },
      { property: "og:title", content: "Live evaluation | AEGIS Trust Console" },
      { property: "og:description", content: "Verify AI answers against real evidence." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: pageSeo("/evaluation").links,
  }),
  component: Evaluation,
});
