import { createFileRoute } from "@tanstack/react-router";
import { FactLockPage } from "@/components/aegis/fact-lock";
import { pageSeo } from "@/lib/seo";
export const Route = createFileRoute("/facts")({
  head: () => ({
    meta: [
      ...pageSeo("/facts").meta,
      { title: "Fact Lock | AEGIS Trust Console" },
      {
        name: "description",
        content: "Approved, versioned facts every AI answer is checked against.",
      },
      { property: "og:title", content: "Fact Lock | AEGIS Trust Console" },
      { property: "og:type", content: "website" },
    ],
    links: pageSeo("/facts").links,
  }),
  component: () => <FactLockPage />,
});
