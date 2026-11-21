import { createFileRoute } from "@tanstack/react-router";
import { Overview } from "@/components/aegis/workspaces";
import { pageSeo } from "@/lib/seo";

// The home route ships no og:image, so serve-time hosting can inject the
// project's social preview (explicit og:image or latest screenshot).
export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      ...pageSeo("/").meta,
      { title: "Overview | AEGIS Trust Console" },
      {
        name: "description",
        content:
          "Monitor AI reliability, decision outcomes, and evidence-backed intelligence with AEGIS.",
      },
      { property: "og:title", content: "Overview | AEGIS Trust Console" },
      {
        property: "og:description",
        content:
          "Monitor AI reliability, decision outcomes, and evidence-backed intelligence with AEGIS.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: pageSeo("/").links,
  }),
  component: Overview,
});
