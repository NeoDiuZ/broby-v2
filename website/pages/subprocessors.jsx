/**
 * @file pages/subprocessors.jsx
 * @description Public sub-processor list. Extracts and renders just the
 * "Annex A — Sub-processors" section from the DPA markdown. Source-of-truth
 * is the DPA itself (Annex A); this page is a curated view of that table.
 *
 * Footer note clarifies the rendering relationship: when DPA Annex A is
 * updated in BrobyVault and synced to website/content/legal/dpa.md, this
 * page reflects the change automatically on next deploy.
 *
 * NOTE on "Last updated" column: the DPA source markdown lists Sub-processor /
 * Role / Region only — it does NOT track per-row last-updated dates. We surface
 * the document-level last-updated date below the table rather than fabricating
 * per-row dates. Flagged as [VERIFY] in the deliverable.
 */
import { LegalDocPage } from '../components/legal/LegalDocPage.jsx'
import { renderSubprocessorsAnnex } from '../lib/legal.js'

export async function getStaticProps() {
  const html = renderSubprocessorsAnnex()
  return { props: { html } }
}

export default function SubprocessorsPage({ html }) {
  return (
    <LegalDocPage
      title="Sub-processors"
      version="v2.0"
      effectiveDate="6 May 2026"
      lastUpdated="6 May 2026"
      description="The list of sub-processors Broby Pte. Ltd. engages to deliver the BrobyVets service. Mirrors Annex A of the Data Processing Agreement."
      html={html}
      footerNote="This page mirrors Annex A of the Broby Data Processing Agreement. It is updated automatically when DPA Annex A is updated."
    />
  )
}
