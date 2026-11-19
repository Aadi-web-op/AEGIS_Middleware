import { createFileRoute } from "@tanstack/react-router";
import { DataWorkspace } from "@/components/aegis/workspaces";
export const Route = createFileRoute("/escalations")({
  head: () => ({
    meta: [
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
  }),
  component: () => <DataWorkspace kind="escalations" />,
});
