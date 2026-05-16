import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppBackdrop } from "@/components/AppBackdrop";
import { Nav } from "@/components/Nav";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "QueryMesh",
  description: "Web UI for the QueryMesh API (signup, keys, chat)",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
    shortcut: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-svh">
      <body
        className={`${geistSans.variable} ${geistMono.variable} relative flex h-svh min-h-0 flex-col overflow-hidden bg-zinc-950 font-sans antialiased text-zinc-200`}
      >
        <AppBackdrop />
        <Nav />
        <main className="mx-auto flex min-h-0 w-full min-w-0 max-w-[min(100%,92.5rem)] flex-1 flex-col overflow-y-auto px-4 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}
