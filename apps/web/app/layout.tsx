import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Shell } from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "clip_star",
  description: "Turn long videos into clips, publish them across every account, and learn what works.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon-192.png", apple: "/icon-192.png" },
  appleWebApp: { capable: true, title: "clip_star", statusBarStyle: "default" },
};

export const viewport: Viewport = { themeColor: "#14202a" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
