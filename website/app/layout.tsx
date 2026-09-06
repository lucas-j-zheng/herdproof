import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'HerdProof — Drone-assisted livestock review for agricultural lending',
  description: 'Explore how drone imagery can support livestock evidence review: cattle observations, overlapping-photo matching, human review, and exportable assessments. An independent prototype by Lucas Zheng.',
  openGraph: {
    title: 'HerdProof — Get closer to the farm behind the loan',
    description: 'Drone-assisted livestock review for agricultural lending. Inspect the approach, a real prototype result, and the evidence behind it.',
    type: 'website', locale: 'en_US',
  },
  icons: { icon: '/favicon.svg' },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
