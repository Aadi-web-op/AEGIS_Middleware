import { createFileRoute } from "@tanstack/react-router";
import { Pricing } from "@/components/aegis/pricing";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/pricing")({
  head: () => ({
    meta: [
      ...pageSeo("/pricing").meta,
      { title: "Plans & Pricing | AEGIS Trust Console" },
      {
        name: "description",
        content:
          "AEGIS plans: free open-source core, hosted design-partner pilots, Business and Enterprise.",
      },
      { property: "og:title", content: "Plans & Pricing | AEGIS Trust Console" },
      {
        property: "og:description",
        content:
          "AEGIS plans: free open-source core, hosted design-partner pilots, Business and Enterprise.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: pageSeo("/pricing").links,
  }),
  component: Pricing,
});
