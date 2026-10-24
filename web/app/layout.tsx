import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "hiyo — your personal health companion",
  description: "An AI secretary with a sense of timing.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
