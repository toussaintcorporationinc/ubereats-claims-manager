import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "TENNET",
    short_name: "TENNET",
    description: "Cockpit de suivi des reclamations et recuperations Uber Eats.",
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#f4f6f8",
    theme_color: "#138a61",
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
      },
    ],
  };
}
