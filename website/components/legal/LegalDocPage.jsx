/**
 * @file LegalDocPage.jsx
 * @description Shared chrome for the four public legal pages:
 *   /privacy, /terms, /dpa, /subprocessors.
 * Renders sanitised markdown HTML produced by lib/legal.js inside a
 * BROBY_DESIGN_SYSTEM.md-styled page (cream bg #F5F3EF, teal #0D9488,
 * Plus Jakarta Sans body font). Marketing-site pages still use the
 * existing aqua palette — only legal pages opt into the design system.
 *
 * @page /privacy /terms /dpa /subprocessors
 * @props
 *   - title: string — page title shown in <h1> and <title>
 *   - version: string — e.g. "v2.0"
 *   - effectiveDate: string — e.g. "5 May 2026"
 *   - lastUpdated: string — e.g. "5 May 2026"
 *   - html: string — sanitised body HTML (already trusted, set via dangerouslySetInnerHTML)
 *   - description: string — meta description for <head>
 *   - breadcrumbBackHref?: string — defaults to '/'
 *   - footerNote?: string — optional small italic note rendered below body (used by /subprocessors)
 */
import Head from 'next/head'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

const SIBLING_LINKS = [
  { href: '/privacy', label: 'Privacy Policy' },
  { href: '/terms', label: 'Terms of Service' },
  { href: '/dpa', label: 'Data Processing Agreement' },
  { href: '/subprocessors', label: 'Sub-processors' },
]

export function LegalDocPage({
  title,
  version,
  effectiveDate,
  lastUpdated,
  html,
  description,
  breadcrumbBackHref = '/',
  footerNote,
}) {
  return (
    <>
      <Head>
        <title>{`${title} — Broby Vets`}</title>
        <meta name="description" content={description || `${title} for the Broby Vets service`} />
      </Head>

      <div className="min-h-screen bg-ds-bg font-plus-jakarta text-ds-text-dark">
        {/* Header — design-system surface with subtle border */}
        <header className="bg-ds-surface border-b border-ds-border">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <Link href="/" className="flex items-center gap-2">
                <img src="/images/broby-logo.png" alt="Broby Vets" className="w-8 h-8" />
                <span className="text-xl font-semibold tracking-tight text-ds-primary">Broby Vets</span>
              </Link>
              <Link
                href={breadcrumbBackHref}
                className="flex items-center gap-2 text-[14px] font-medium text-ds-text-muted hover:text-ds-text-dark transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                Back to Home
              </Link>
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight text-ds-text-dark mb-3">
            {title}
          </h1>

          <VersionBlock version={version} effectiveDate={effectiveDate} lastUpdated={lastUpdated} />

          <article className="legal-prose mt-8" dangerouslySetInnerHTML={{ __html: html }} />

          {footerNote && (
            <p className="mt-10 text-[13px] italic text-ds-text-muted">{footerNote}</p>
          )}

          <SiblingLinks currentPath={breadcrumbBackHref === '/' ? null : breadcrumbBackHref} />
        </main>

        {/* Footer */}
        <footer className="bg-ds-surface border-t border-ds-border py-8 mt-16">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col md:flex-row justify-between items-center gap-4">
            <div className="flex items-center gap-2">
              <img src="/images/broby-logo.png" alt="Broby Vets" className="w-6 h-6" />
              <span className="text-[13px] text-ds-text-muted">
                © {new Date().getFullYear()} Broby Pte. Ltd. UEN 202531542D.
              </span>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-[13px]">
              {SIBLING_LINKS.map((l) => (
                <Link key={l.href} href={l.href} className="text-ds-text-muted hover:text-ds-text-dark transition-colors">
                  {l.label}
                </Link>
              ))}
              <Link href="/contact" className="text-ds-text-muted hover:text-ds-text-dark transition-colors">
                Contact
              </Link>
            </div>
          </div>
        </footer>
      </div>
    </>
  )
}

function VersionBlock({ version, effectiveDate, lastUpdated }) {
  return (
    <div className="inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] font-medium text-ds-text-muted bg-ds-surface border border-ds-border rounded-ds-lg px-3 py-2 shadow-ds-card">
      <span className="text-ds-primary font-semibold">{version}</span>
      <span aria-hidden="true" className="text-ds-text-light">•</span>
      <span>Effective {effectiveDate}</span>
      <span aria-hidden="true" className="text-ds-text-light">•</span>
      <span>Last updated {lastUpdated}</span>
    </div>
  )
}

function SiblingLinks() {
  return (
    <nav aria-label="Related legal documents" className="mt-12 pt-8 border-t border-ds-border">
      <p className="text-[11px] font-semibold tracking-[0.2em] uppercase text-ds-text-light mb-3">
        Other policies
      </p>
      <ul className="flex flex-wrap gap-x-6 gap-y-2">
        {SIBLING_LINKS.map((l) => (
          <li key={l.href}>
            <Link href={l.href} className="text-[14px] text-ds-primary hover:text-ds-primary-hover underline-offset-2 hover:underline">
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
