/**
 * @file lib/legal.js
 * @description Server-side helpers for rendering BrobyVault legal markdown
 * into sanitised HTML at build time (Next.js getStaticProps).
 *
 * Source-of-truth: /Users/hyugakuramochi/BrobyVault/Drafts/{Privacy-Policy,Terms-of-Service,Data-Processing-Agreement}-v2-DRAFT.md
 * Deployment copies live in website/content/legal/ (committed to repo so Railway can read at build time).
 * When BrobyVault drafts change, sync to website/content/legal/ and redeploy.
 */
import fs from 'fs'
import path from 'path'
import { marked } from 'marked'
import sanitizeHtml from 'sanitize-html'

const LEGAL_DIR = path.join(process.cwd(), 'content', 'legal')

/**
 * Render a legal markdown file to sanitised HTML.
 * @param {string} slug — one of 'privacy' | 'terms' | 'dpa'
 * @returns {string} sanitised HTML
 */
export function renderLegalMarkdown(slug) {
  const filePath = path.join(LEGAL_DIR, `${slug}.md`)
  const md = fs.readFileSync(filePath, 'utf8')
  // Strip the document's own H1 + version block (lines 1-7) since the
  // LegalDocPage renders them in a styled header instead. Source markdown
  // structure (verified 2026-05-07): line 1 = "# <Title>", lines 3-5 = entity
  // + version + last-updated, line 7 = "---" horizontal rule.
  const stripped = stripFrontMatter(md)
  const rawHtml = marked.parse(stripped, { gfm: true, breaks: false })
  return sanitiseLegalHtml(rawHtml)
}

/**
 * Extract just the Annex A sub-processor table from the DPA markdown.
 * Used by /subprocessors page.
 * @returns {string} sanitised HTML containing the Annex A table only
 */
export function renderSubprocessorsAnnex() {
  const filePath = path.join(LEGAL_DIR, 'dpa.md')
  const md = fs.readFileSync(filePath, 'utf8')
  const annexA = extractSection(md, '# Annex A — Sub-processors', '# Annex B')
  if (!annexA) {
    throw new Error('Could not extract Annex A from dpa.md — section markers changed?')
  }
  const rawHtml = marked.parse(annexA, { gfm: true, breaks: false })
  return sanitiseLegalHtml(rawHtml)
}

function stripFrontMatter(md) {
  const lines = md.split('\n')
  // Drop everything up to and including the first "---" horizontal rule.
  const hrIdx = lines.findIndex((line, i) => i > 0 && line.trim() === '---')
  if (hrIdx === -1) return md
  return lines.slice(hrIdx + 1).join('\n').trimStart()
}

function extractSection(md, startMarker, endMarker) {
  const startIdx = md.indexOf(startMarker)
  if (startIdx === -1) return null
  const afterStart = md.slice(startIdx + startMarker.length)
  const endIdx = afterStart.indexOf(endMarker)
  return endIdx === -1 ? afterStart : afterStart.slice(0, endIdx)
}

function sanitiseLegalHtml(html) {
  return sanitizeHtml(html, {
    allowedTags: [
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'p', 'a', 'ul', 'ol', 'li',
      'strong', 'em', 'b', 'i', 'u', 'br', 'hr',
      'blockquote', 'code', 'pre',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'span', 'div',
    ],
    allowedAttributes: {
      a: ['href', 'name', 'target', 'rel', 'id'],
      '*': ['id'],
    },
    allowedSchemes: ['http', 'https', 'mailto', 'tel'],
    transformTags: {
      a: sanitizeHtml.simpleTransform('a', { target: '_blank', rel: 'noopener noreferrer' }, true),
    },
  })
}
