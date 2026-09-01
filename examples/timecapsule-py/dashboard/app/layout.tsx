import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TimeCapsule · Reliability workspace",
  description: "Explore the futures where an AI agent fails before your users do.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
