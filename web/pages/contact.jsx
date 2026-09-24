import Head from 'next/head'
import Link from 'next/link'
import { ArrowLeft, Mail, Phone, MapPin } from 'lucide-react'
import { useRef, useState } from 'react'

export default function Contact() {
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    company: '',
    subject: 'Book a Demo',
    message: ''
  })
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const pendingSubmission = useRef({ key: '', payload: '' })

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')

    try {
      const payload = JSON.stringify(formData)
      if (pendingSubmission.current.payload !== payload) {
        pendingSubmission.current = { key: crypto.randomUUID(), payload }
      }
      const response = await fetch('/api/marketing/leads/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          submission_key: pendingSubmission.current.key,
          contact_name: formData.name,
          clinic_name: formData.company,
          country: 'other',
          contact_channel: 'email',
          contact_handle: formData.email,
          subject: formData.subject,
          message: formData.message,
        }),
      })
      if (!response.ok || !(await response.json()).received) {
        throw new Error('We could not save your enquiry. Please try again or email contact@brobyvets.com.')
      }
      setSubmitted(true)
      pendingSubmission.current = { key: '', payload: '' }
    } catch (error) {
      setError(error.message || 'We could not save your enquiry. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    })
  }

  return (
    <>
      <Head>
        <title>Contact Us - Broby Vets</title>
        <meta name="description" content="Get in touch with Broby Vets for enterprise solutions and support" />
      </Head>

      <div className="min-h-screen bg-background">
        {/* Header */}
        <header className="border-b border-border bg-white">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <Link href="/" className="flex items-center gap-2">
                <img src="/images/broby-logo.png" alt="Broby Vets Logo" className="w-8 h-8" />
                <span className="text-xl font-bold" style={{color: '#14aeb6'}}>Broby Vets</span>
              </Link>
              <Link href="/" className="flex items-center gap-2 text-text-secondary hover:text-text-primary transition-colors">
                <ArrowLeft className="w-4 h-4" />
                Back to Home
              </Link>
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
          <div className="grid md:grid-cols-2 gap-12">
            {/* Contact Information */}
            <div>
              <h1 className="text-3xl font-bold text-text-primary mb-6">
                Get in Touch
              </h1>

              <p className="text-text-secondary mb-8">
                Have questions about our Enterprise plan or need a custom solution for your clinic?
                We're here to help you streamline your veterinary practice.
              </p>

              <div className="space-y-6">
                <div className="flex items-start gap-4">
                  <Mail className="w-6 h-6 text-primary mt-1" />
                  <div>
                    <h3 className="font-semibold text-text-primary mb-1">Email</h3>
                    <a href="mailto:contact@brobyvets.com" className="text-primary hover:underline">
                      contact@brobyvets.com
                    </a>
                  </div>
                </div>

              </div>

              <div className="mt-8 p-6 bg-background-secondary rounded-xl">
                <h3 className="font-semibold text-text-primary mb-2">
                  Response Time
                </h3>
                <p className="text-text-secondary">
                  Our team reviews enquiries during business hours. This form is
                  not monitored for medical emergencies.
                </p>
              </div>
            </div>

            {/* Contact Form */}
            <div>
              {submitted ? (
                <div className="bg-green-50 border border-green-200 rounded-lg p-6 text-center">
                  <h3 className="text-lg font-semibold text-green-800 mb-2">
                    Enquiry received
                  </h3>
                  <p className="text-green-700">
                    Your enquiry is saved for our team. We will reply by email.
                  </p>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-text-primary mb-2">
                      Name *
                    </label>
                    <input
                      type="text"
                      name="name"
                      value={formData.name}
                      onChange={handleChange}
                      required
                      className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-text-primary mb-2">
                      Email *
                    </label>
                    <input
                      type="email"
                      name="email"
                      value={formData.email}
                      onChange={handleChange}
                      required
                      className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-text-primary mb-2">
                      Company/Clinic Name
                    </label>
                    <input
                      type="text"
                      name="company"
                      value={formData.company}
                      onChange={handleChange}
                      className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-text-primary mb-2">
                      Subject
                    </label>
                    <select
                      name="subject"
                      value={formData.subject}
                      onChange={handleChange}
                      className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                    >
                      <option value="Book a Demo">Book a Demo</option>
                      <option value="Enterprise Plan Inquiry">Enterprise Plan Inquiry</option>
                      <option value="Technical Support">Technical Support</option>
                      <option value="General Inquiry">General Inquiry</option>
                      <option value="Partnership">Partnership Opportunity</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-text-primary mb-2">
                      Message *
                    </label>
                    <textarea
                      name="message"
                      value={formData.message}
                      onChange={handleChange}
                      required
                      rows={4}
                      className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                      placeholder="Tell us about your clinic's needs..."
                    />
                  </div>

                  {error && <p role="alert" className="text-red-700">{error}</p>}
                  <p className="text-sm text-text-secondary">We use your details to reply to this enquiry. <Link href="/privacy" className="underline">Privacy policy</Link>.</p>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="w-full bg-primary hover:bg-primary-dark text-white font-medium py-3 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {submitting ? 'Sending...' : 'Send Message'}
                  </button>
                </form>
              )}
            </div>
          </div>
        </main>

        {/* Footer */}
        <footer className="bg-background-secondary border-t border-border py-8 mt-16">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col md:flex-row justify-between items-center">
              <div className="mb-4 md:mb-0">
                <div className="flex items-center gap-2 mb-2">
                  <img src="/images/broby-logo.png" alt="Broby Vets Logo" className="w-6 h-6" />
                  <div className="text-lg font-bold" style={{color: '#14aeb6'}}>
                    Broby Vets
                  </div>
                </div>
                <p className="text-text-secondary text-sm">
                  © 2026 Broby Vets. All rights reserved.
                </p>
              </div>

              <div className="flex gap-6">
                <Link href="/terms" className="text-text-secondary hover:text-text-primary transition-colors">
                  Terms
                </Link>
                <Link href="/privacy" className="text-text-secondary hover:text-text-primary transition-colors">
                  Privacy
                </Link>
                <Link href="/contact" className="text-text-secondary hover:text-text-primary transition-colors">
                  Contact
                </Link>
              </div>
            </div>
          </div>
        </footer>
      </div>
    </>
  )
}
