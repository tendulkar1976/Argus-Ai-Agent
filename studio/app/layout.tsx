import type { Metadata } from "next";
import "./studio.css";
export const metadata: Metadata = {
  title: "Argus-AI Studio",
  description: "Trace-aware LLM execution and quality-constrained experiments",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
