import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "TENNET",
    short_name: "TENNET",
    description: "Cockpit de suivi des reclamations et recuperations Uber Eats.",
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#ffffff",
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icons/icon-1024.png",
        sizes: "1024x1024",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    screenshots: [
      {
        src: "/splash/splash-1290x2796.png",
        sizes: "1290x2796",
        type: "image/png",
        form_factor: "narrow",
      },
      {
        src: "/splash/splash-2048x2732.png",
        sizes: "2048x2732",
        type: "image/png",
        form_factor: "wide",
      },
    ],
  };
}
