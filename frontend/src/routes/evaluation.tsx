import { createFileRoute } from "@tanstack/react-router";
import { Evaluation } from "@/components/aegis/workspaces";
export const Route = createFileRoute("/evaluation")({
  head: () => ({
    meta: [
      { title: "Live evaluation | AEGIS Trust Console" },
      { name: "description", content: "Verify AI answers against real evidence." },
      { property: "og:title", content: "Live evaluation | AEGIS Trust Console" },
      { property: "og:description", content: "Verify AI answers against real evidence." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Evaluation,
});
