// Per-page canonical URL and share-preview image. Set VITE_SITE_URL when the console moves to
// another domain; public/sitemap.xml and public/robots.txt list the same origin.
export const SITE_URL = (
  import.meta.env["VITE_SITE_URL"] ?? "https://aegis-middlewate.vercel.app"
).replace(/\/+$/, "");
const OG_IMAGE = `${SITE_URL}/og-image.png`;

export function pageSeo(path: string) {
  const url = `${SITE_URL}${path === "/" ? "/" : path}`;
  return {
    meta: [
      { property: "og:url", content: url },
      { property: "og:image", content: OG_IMAGE },
      { property: "og:image:width", content: "1200" },
      { property: "og:image:height", content: "630" },
      { property: "og:image:alt", content: "AEGIS Trust Console" },
      { name: "twitter:image", content: OG_IMAGE },
    ],
    links: [{ rel: "canonical", href: url }],
  };
}
