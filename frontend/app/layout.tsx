import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

const geist = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "DeckPilot — AI co-pilot for PDF → PPT",
  description:
    "Turn any teaching PDF into a polished slide deck. Review every page and slide before you generate — you stay in control.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geist.variable} h-full`}>
      <body className="min-h-full antialiased">
        {/* Fixed ambient glow behind everything — pointer-events-none */}
        <div className="ambient-bg" aria-hidden="true">
          <div className="ambient-orb-3" />
        </div>
        <div className="relative z-10">{children}</div>
      </body>
    </html>
  );
}
