import type { Metadata, Viewport } from "next";
import { AuthGate } from "@/components/AuthGate";
import { BriefBanner } from "@/components/BriefBanner";
import { Nav } from "@/components/Nav";
import { PwaRegister } from "@/components/PwaRegister";
import "./globals.css";

export const metadata: Metadata = {
  title: "Recall",
  description: "Voice-first learning companion",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Recall", statusBarStyle: "default" },
  icons: {
    icon: [{ url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">
        <PwaRegister />
        <AuthGate>
          <Nav />
          <BriefBanner />
          {children}
        </AuthGate>
      </body>
    </html>
  );
}
